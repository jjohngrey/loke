"use client";

import { useEffect, useRef, useState } from "react";
import type { RuntimeRequest, RuntimeResetResult } from "@loke/contracts";
import { applyRunEvent, emptyDisplay, readRunEvents, type RuntimeDisplay } from "./runtime-client";

type ChatRun = {
  request: RuntimeRequest;
  display: RuntimeDisplay;
  phase: "running" | "offline" | "idle" | "resetting";
  error?: string;
  controller?: AbortController;
  cancelRequested?: boolean;
  cancellationSent?: boolean;
};

async function post(path: string, payload: unknown, signal?: AbortSignal) {
  const response = await fetch(`/api/backend/runtime/${path}`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(payload), signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "The chat request could not be processed.");
  }
  return response;
}

export function useRuntimeChat(onDisplay: (chatId: string, requestId: string, display: RuntimeDisplay) => void) {
  const [runs, setRuns] = useState<Record<string, ChatRun>>({});
  const records = useRef<Record<string, ChatRun>>({});
  const sessions = useRef<Record<string, { id: string; epoch: number }>>({});
  const listener = useRef(onDisplay);
  listener.current = onDisplay;

  function update(chatId: string, record: ChatRun) {
    records.current[chatId] = record;
    setRuns((items) => ({ ...items, [chatId]: record }));
  }

  function isCurrent(chatId: string, record: ChatRun) {
    return records.current[chatId] === record &&
      sessions.current[chatId]?.id === record.request.session_id &&
      sessions.current[chatId]?.epoch === record.request.session_epoch;
  }

  async function connect(chatId: string, record: ChatRun) {
    record.controller = new AbortController();
    record.phase = "running";
    record.error = undefined;
    update(chatId, record);
    try {
      const response = await post("run", record.request, record.controller.signal);
      await readRunEvents(response, (event) => {
        if (!isCurrent(chatId, record) || event.session_epoch !== record.request.session_epoch ||
            event.request_id !== record.request.request_id) return;
        record.display = applyRunEvent(record.display, event);
        if (record.cancelRequested && !record.cancellationSent && !record.display.outcome)
          void cancel(chatId);
        listener.current(chatId, record.request.request_id, record.display);
        if (record.display.outcome) record.phase = "idle";
        update(chatId, record);
      });
      if (isCurrent(chatId, record) && !record.display.outcome)
        throw new Error("Connection lost. Retry to reconnect to this response.");
    } catch (error) {
      if (!isCurrent(chatId, record)) return;
      record.phase = "offline";
      record.error = error instanceof Error ? error.message : "Connection lost. Retry this response.";
      update(chatId, record);
    }
  }

  function submit(chatId: string, text: string) {
    if (["running", "offline", "resetting"].includes(records.current[chatId]?.phase)) return false;
    const session = sessions.current[chatId] ||= { id: crypto.randomUUID(), epoch: 0 };
    const record: ChatRun = {
      request: { session_id: session.id, session_epoch: session.epoch, request_id: crypto.randomUUID(), text },
      display: emptyDisplay(), phase: "running",
    };
    void connect(chatId, record);
    return true;
  }

  async function cancel(chatId: string) {
    const record = records.current[chatId];
    if (!record || record.phase === "idle" || record.phase === "resetting") return;
    record.cancelRequested = true;
    // Wait for reservation acknowledgement so Stop cannot race ahead of the run request.
    if (!record.display.runId) {
      if (record.phase === "offline") void connect(chatId, record);
      return;
    }
    record.cancellationSent = true;
    try {
      await post("cancel", control(record.request));
      if (isCurrent(chatId, record) && record.phase === "offline") void connect(chatId, record);
    } catch (error) {
      if (isCurrent(chatId, record)) {
        record.cancellationSent = false;
        record.error = error instanceof Error ? error.message : "Cancellation failed. Retry.";
        update(chatId, record);
      }
    }
  }

  function control(request: RuntimeRequest) {
    const { text: _text, ...payload } = request;
    return payload;
  }

  async function reset(chatId: string): Promise<boolean> {
    const session = sessions.current[chatId];
    if (!session) return true;
    const record = records.current[chatId];
    if (record?.phase === "resetting") return false;
    // Invalidate callbacks immediately; aborting only detaches the subscriber.
    const priorEpoch = session.epoch;
    session.epoch += 1;
    if (record) {
      record.controller?.abort();
      update(chatId, { ...record, phase: "resetting", error: undefined });
    }
    try {
      const response = await post("reset", { session_id: session.id, session_epoch: priorEpoch });
      const result = await response.json() as RuntimeResetResult;
      session.epoch = result.session_epoch;
      delete records.current[chatId];
      setRuns((items) => {
        const next = { ...items };
        delete next[chatId];
        return next;
      });
      return true;
    } catch {
      // The reset may have reached the server. Rotate the session rather than reuse an uncertain epoch.
      sessions.current[chatId] = { id: crypto.randomUUID(), epoch: 0 };
      if (record) {
        void post("cancel", control(record.request)).catch(() => {});
        update(chatId, { ...record, phase: "idle", controller: undefined,
          error: "The previous reset could not be confirmed. A new chat session has started." });
      }
      return true;
    }
  }

  function retry(chatId: string) {
    const record = records.current[chatId];
    if (record?.phase === "offline") void connect(chatId, record);
  }

  useEffect(() => () => {
    for (const record of Object.values(records.current)) {
      record.controller?.abort();
      if (record.phase === "running" || record.phase === "offline") {
        void fetch("/api/backend/runtime/cancel", {
          method: "POST", headers: { "content-type": "application/json" }, keepalive: true,
          body: JSON.stringify(control(record.request)),
        }).catch(() => {});
      }
    }
    records.current = {};
  }, []);

  return { runs, submit, retry, cancel, reset };
}
