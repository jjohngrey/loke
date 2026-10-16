"use client";
import { useEffect, useRef, useState } from "react";
import type {
  LearningInput,
  TranscriptionResult,
  UploadPreview,
} from "@loke/contracts";
import { api } from "./use-workspace";

export function useMediaInput(
  generation: string | undefined,
  enabled: boolean,
  apply: (text: string, mode: LearningInput["mode"], label: string) => void,
) {
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");
  const [consent, setConsent] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const request = useRef<AbortController | null>(null);
  const version = useRef(0);
  const applying = useRef(apply);
  applying.current = apply;
  const active = useRef(enabled);
  active.current = enabled;
  function release() {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }
  function cancel() {
    version.current += 1;
    request.current?.abort();
    request.current = null;
    const r = recorder.current;
    recorder.current = null;
    if (r) {
      r.onstop = null;
      r.ondataavailable = null;
      if (r.state !== "inactive") r.stop();
    }
    release();
    setState("idle");
  }
  useEffect(() => {
    cancel();
    setConsent(false);
    return cancel;
  }, [generation, enabled]); // Cancel late permission grants and requests on reset/unmount.
  async function process(file: File) {
    if (!active.current) return;
    const audio = /\.(mp3|mp4|m4a|wav|webm)$/i.test(file.name);
    if (audio && !consent) {
      setError("Consent to OpenAI audio processing before choosing audio.");
      return;
    }
    if (!file.size || file.size > (audio ? 1_000_000 : 5_000_000)) {
      setError(
        audio
          ? "Choose nonempty audio under 1 MB."
          : "Choose a nonempty file under 5 MB.",
      );
      return;
    }
    const start = ++version.current;
    setError("");
    setState(audio ? "transcribing" : "reading attachment");
    const controller = new AbortController();
    request.current = controller;
    const deadline = setTimeout(() => controller.abort(), 35000);
    try {
      const body = new FormData();
      body.append("file", file);
      const result = await api<TranscriptionResult | UploadPreview>(
        audio ? "audio/transcribe" : "attachments/preview",
        {
          method: "POST",
          body,
          signal: controller.signal,
          headers: {
            "generation-id": generation || "",
            ...(audio ? { "audio-consent": "true" } : {}),
          },
        },
      );
      if (start === version.current && active.current)
        applying.current(
          result.text,
          audio ? "voice" : "attachment",
          file.name,
        );
    } catch (e) {
      if (start === version.current)
        setError(
          e instanceof Error && e.name === "AbortError"
            ? "Processing stopped. Your previous draft is unchanged."
            : (e as Error).message,
        );
    } finally {
      clearTimeout(deadline);
      if (start === version.current) {
        request.current = null;
        setState("idle");
      }
    }
  }
  async function record() {
    if (recorder.current?.state === "recording") {
      setState("stopping");
      recorder.current.stop();
      return;
    }
    if (!consent) {
      setError("Consent to audio processing before recording.");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError(
        "Microphone recording is unavailable here. Upload an audio file or type instead.",
      );
      return;
    }
    const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find(
      (t) => MediaRecorder.isTypeSupported(t),
    );
    if (!mime) {
      setError("No supported recording format. Upload audio or type instead.");
      return;
    }
    const start = ++version.current;
    setState("requesting microphone");
    setError("");
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (start !== version.current || !active.current) {
        media.getTracks().forEach((t) => t.stop());
        return;
      }
      stream.current = media;
      const r = new MediaRecorder(media, {
        mimeType: mime,
        audioBitsPerSecond: 64000,
      });
      recorder.current = r;
      const chunks: Blob[] = [];
      let bytes = 0;
      let oversized = false;
      r.ondataavailable = (e) => {
        bytes += e.data.size;
        if (bytes > 1_000_000) {
          oversized = true;
          if (r.state === "recording") r.stop();
        } else if (e.data.size) chunks.push(e.data);
      };
      r.onerror = () => {
        if (start === version.current) {
          cancel();
          setError("Recording failed. Try uploading audio or typing.");
        }
      };
      r.onstop = () => {
        release();
        recorder.current = null;
        if (start !== version.current) return;
        if (oversized) {
          setError("Recording exceeded 1 MB. Try a shorter clip.");
          setState("idle");
          return;
        }
        const file = new File(
          chunks,
          `recording.${mime.includes("mp4") ? "m4a" : "webm"}`,
          { type: mime },
        );
        void process(file);
      };
      r.start(250);
      setState("recording");
      timer.current = setTimeout(() => {
        if (r.state === "recording") {
          setState("stopping");
          r.stop();
        }
      }, 30000);
    } catch {
      if (start === version.current) {
        release();
        setState("idle");
        setError(
          "Microphone access failed. Allow access or type your message.",
        );
      }
    }
  }
  return {
    state,
    error,
    consent,
    setConsent,
    fileRef,
    process,
    record,
    cancel,
  };
}
