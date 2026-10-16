"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AppCapabilities,
  ChatSettings,
  FolderInput,
  GoalInput,
  HistoryPage,
  LearningInput,
  LearningView,
  WorkspaceView,
} from "@loke/contracts";

export type Message = {
  id: string;
  role: "user" | "loke";
  text: string;
  sequence: number;
};
export type Chat = {
  id: string;
  title: string;
  folderId?: string;
  messages: Message[];
  hasMore?: boolean;
};
export type Folder = { id: string; name: string };
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    ...init,
    cache: "no-store",
    signal: init.signal ?? AbortSignal.timeout(35000),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    throw new ApiError(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((d: { msg?: string }) => d.msg || "Invalid input")
              .join("; ")
          : "The request failed.",
      response.status,
    );
  }
  return data as T;
}
const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export function useWorkspace(activeId: string | null, onReset: () => void) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [view, setView] = useState<LearningView | null>(null);
  const [capabilities, setCapabilities] = useState<AppCapabilities | null>(
    null,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [hasMoreChats, setHasMoreChats] = useState(false);
  const [canRetry, setCanRetry] = useState(false);
  const current = useRef<LearningView | null>(null);
  const epoch = useRef(0);
  const pending = useRef<{ path: string; init: RequestInit } | null>(null);
  const locked = useRef(false);
  const loadedPages = useRef(1);
  const active = useRef(activeId);
  active.current = activeId;
  const resetCallback = useRef(onReset);
  resetCallback.current = onReset;
  const applyView = useCallback((next: LearningView) => {
    const old = current.current;
    if (old && old.generation_id !== next.generation_id) {
      epoch.current += 1;
      pending.current = null;
      setCanRetry(false);
      setChats([]);
      setFolders([]);
      resetCallback.current();
    }
    if (
      !old ||
      old.generation_id !== next.generation_id ||
      next.state_revision >= old.state_revision
    ) {
      current.current = next;
      setView(next);
    }
  }, []);
  const loadHistory = useCallback(
    async (id: string, generation: string, before?: number) => {
      const start = epoch.current;
      const page = await api<HistoryPage>(
        `chats/history?chat_id=${encodeURIComponent(id)}&generation_id=${encodeURIComponent(generation)}${before ? `&before=${before}` : ""}`,
      );
      if (
        start !== epoch.current ||
        current.current?.generation_id !== page.generation_id
      )
        return;
      setChats((items) =>
        items.map((chat) => {
          if (chat.id !== id) return chat;
          const messages = new Map(chat.messages.map((m) => [m.id, m]));
          for (const m of page.messages)
            messages.set(m.id, {
              ...m,
              role: m.role === "assistant" ? "loke" : "user",
            });
          return {
            ...chat,
            messages: [...messages.values()].sort(
              (a, b) => a.sequence - b.sequence,
            ),
            hasMore:
              before || !chat.messages.length ? page.has_more : chat.hasMore,
          };
        }),
      );
    },
    [],
  );
  const refresh = useCallback(
    async (offset = 0) => {
      const start = epoch.current;
      const [next, pages, caps] = await Promise.all([
        api<LearningView>("view"),
        Promise.all(
          Array.from({ length: offset ? 1 : loadedPages.current }, (_, i) =>
            api<WorkspaceView>(`workspace?offset=${offset || i * 100}`),
          ),
        ),
        api<AppCapabilities>("capabilities"),
      ]);
      if (start !== epoch.current) return;
      const workspace = {
        ...pages[pages.length - 1],
        chats: pages.flatMap((p) => p.chats),
      };
      if (pages.some((p) => p.generation_id !== next.generation_id)) return;
      applyView(next);
      if (workspace.generation_id !== next.generation_id) return;
      setCapabilities(caps);
      setFolders(workspace.folders);
      setHasMoreChats(!!workspace.has_more);
      setChats((previous) => {
        const old = new Map(previous.map((c) => [c.id, c]));
        const incoming = workspace.chats.map((c) => ({
          id: c.id,
          title: c.title,
          folderId: c.folder_id ?? undefined,
          messages: old.get(c.id)?.messages ?? [],
          hasMore: old.get(c.id)?.hasMore,
        }));
        return offset
          ? [
              ...previous.filter((c) => !incoming.some((n) => n.id === c.id)),
              ...incoming,
            ]
          : incoming;
      });
      setReady(true);
      if (active.current)
        await loadHistory(active.current, next.generation_id!);
    },
    [applyView, loadHistory],
  );
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      if (locked.current || !alive) return;
      locked.current = true;
      try {
        await refresh();
      } catch (e) {
        if (alive) setError((e as Error).message);
      } finally {
        locked.current = false;
      }
    };
    void poll();
    const timer = setInterval(poll, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
      epoch.current += 1;
    };
  }, [refresh]);
  useEffect(() => {
    if (activeId && current.current)
      void loadHistory(activeId, current.current.generation_id!).catch((e) =>
        setError(e.message),
      );
  }, [activeId, loadHistory]);
  const execute = async (path: string, init: RequestInit, retry = false) => {
    if (locked.current)
      throw new Error("Please wait for the current operation.");
    if (pending.current && !retry)
      throw new Error(
        "Retry the pending save or discard it before sending a new action.",
      );
    locked.current = true;
    setBusy(true);
    setError("");
    pending.current = { path, init };
    const start = epoch.current;
    try {
      await api<unknown>(path, init);
      if (start !== epoch.current) return false;
      await refresh();
      pending.current = null;
      setCanRetry(false);
      return true;
    } catch (e) {
      const failure = e as ApiError;
      const uncertain = !failure.status || failure.status >= 500;
      setCanRetry(uncertain);
      if (!uncertain) {
        pending.current = null;
        if (failure.status === 409) await refresh();
      }
      setError(failure.message);
      return false;
    } finally {
      locked.current = false;
      setBusy(false);
    }
  };
  const guard = () => ({
    generation_id: current.current?.generation_id,
    expected_state_revision: current.current?.state_revision,
  });
  const scope = (id: string) => ({
    chat_id: id,
    folder_path: (() => {
      const folder = folders.find(
        (f) => f.id === chats.find((c) => c.id === id)?.folderId,
      );
      return folder ? ([folder.name] as [string]) : ([] as []);
    })(),
  });
  return {
    chats,
    folders,
    view,
    capabilities,
    error,
    setError,
    busy,
    ready,
    hasMoreChats,
    canRetry,
    loadMoreChats: () =>
      refresh(loadedPages.current * 100)
        .then(() => {
          loadedPages.current += 1;
        })
        .catch((e) => setError(e.message)),
    loadEarlier: (chat: Chat) =>
      loadHistory(
        chat.id,
        current.current!.generation_id!,
        chat.messages[0]?.sequence,
      ).catch((e) => setError(e.message)),
    setup: (goal: string) =>
      execute(
        "goal",
        post({
          ...guard(),
          request_id: crypto.randomUUID(),
          goal,
          storage_consent: true,
          reminders_enabled: false,
          scope: { chat_id: "getting-started" },
        } satisfies GoalInput),
      ),
    send: (
      id: string,
      text: string,
      mode: LearningInput["mode"],
      sourceTitle?: string,
    ) =>
      execute(
        "input",
        post({
          ...guard(),
          request_id: crypto.randomUUID(),
          text,
          mode,
          ...(mode === "attachment" && sourceTitle
            ? { source_title: sourceTitle }
            : {}),
          scope: scope(id),
        } satisfies LearningInput),
      ),
    addFolder: (name: string) =>
      execute(
        "workspace/folder",
        post({
          ...guard(),
          request_id: crypto.randomUUID(),
          id: crypto.randomUUID(),
          name,
        } satisfies FolderInput),
      ),
    moveChat: (chat: Chat, folder: string) =>
      execute(
        "workspace/chat",
        post({
          ...guard(),
          request_id: crypto.randomUUID(),
          id: chat.id,
          title: chat.title,
          folder_id: folder || null,
        } satisfies ChatSettings),
      ),
    answer: (answer: string) =>
      execute(
        "quiz/answer",
        post({
          ...guard(),
          request_id: crypto.randomUUID(),
          card_id: current.current!.active_quiz!.id,
          answer,
          scope: scope(activeId || "study"),
        }),
      ),
    reminders: (enabled: boolean) =>
      execute(
        "reminders",
        post({ ...guard(), request_id: crypto.randomUUID(), enabled }),
      ),
    retry: async () => {
      const p = pending.current;
      const chatId =
        p?.path === "input"
          ? (JSON.parse(p.init.body as string).scope.chat_id as string)
          : null;
      return { ok: p ? await execute(p.path, p.init, true) : false, chatId };
    },
    reply: () => current.current?.response || "",
    discardRetry: () => {
      pending.current = null;
      setCanRetry(false);
      setError("");
    },
    reset: async () => {
      epoch.current += 1;
      pending.current = null;
      setCanRetry(false);
      resetCallback.current();
      return execute(
        `learner?generation_id=${encodeURIComponent(current.current!.generation_id!)}`,
        { method: "DELETE" },
      );
    },
  };
}
