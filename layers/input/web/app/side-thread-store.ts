import type { SELECTION_VERSION } from "./selection-index";

export type ThreadMessage = { role: "user" | "assistant"; text: string; complete: boolean };
export type SourceMessage = { id: string; markdown: string; history: { role: "user" | "assistant"; text: string }[] };
export type SelectionAnchor = {
  chatId: string; messageId: string; sourceMarkdown: string; selectedText: string;
  startOffset: number; endOffset: number; streamVersion: typeof SELECTION_VERSION;
  renderedText: string;
  mainHistory: SourceMessage["history"];
};
export type ThreadSession = {
  id: string; anchor: SelectionAnchor; messages: ThreadMessage[]; draft: string;
  status: "ready" | "loading" | "error"; error?: string;
};
export type ThreadResponseInput = {
  anchor: SelectionAnchor; history: ThreadMessage[]; question: string;
  threadId: string; requestId: string; signal: AbortSignal; onDelta: (text: string) => void;
};
export type ThreadAdapter = (input: ThreadResponseInput) => Promise<string>;

/** Deterministic development adapter. The production boundary is injected by the UI. */
export const fakeThreadAdapter: ThreadAdapter = async ({ anchor, question, signal, onDelta }) => {
  const text = `Demo side reply about “${anchor.selectedText}”: ${question}\n\nThis is a simulated response.`;
  for (const part of text.match(/.{1,16}/gs) || []) {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(done, 25);
      function done() { signal.removeEventListener("abort", abort); resolve(); }
      function abort() { clearTimeout(timer); reject(new DOMException("Stopped", "AbortError")); }
      if (signal.aborted) abort(); else signal.addEventListener("abort", abort, { once: true });
    });
    onDelta(part);
  }
  return text;
};

/** All callbacks are scoped to the request object, not whichever panel is visible. */
export class SideThreadStore {
  private sessions: Record<string, ThreadSession> = {};
  private listeners = new Set<() => void>();
  private requests = new Map<string, { id: string; controller: AbortController }>();
  private adapter: ThreadAdapter;
  constructor(adapter: ThreadAdapter) { this.adapter = adapter; }
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  snapshot = () => this.sessions;
  private update(id: string, change: (session: ThreadSession) => ThreadSession) {
    if (!this.sessions[id]) return;
    this.sessions = { ...this.sessions, [id]: change(this.sessions[id]) };
    this.listeners.forEach((listener) => listener());
  }
  create(anchor: SelectionAnchor, draft = "") {
    const id = crypto.randomUUID();
    this.sessions = { ...this.sessions, [id]: { id, anchor, draft, messages: [], status: "ready" } };
    this.listeners.forEach((listener) => listener());
    return id;
  }
  draft(id: string, draft: string) { this.update(id, (session) => ({ ...session, draft })); }
  async send(id: string, question?: string, retry = false) {
    const session = this.sessions[id];
    if (!session || this.requests.has(id) || (!retry && session.status === "error")) return;
    const text = (question ?? session.draft).trim();
    if (!retry && !text) return;
    const previous = retry ? session.messages.slice(0, -2) : session.messages;
    const current = retry ? session.messages.at(-2)?.text : text;
    if (!current) return;
    const request = { id: crypto.randomUUID(), controller: new AbortController() };
    this.requests.set(id, request);
    this.update(id, (item) => ({ ...item, draft: retry ? item.draft : "", status: "loading", error: undefined,
      messages: [...previous, { role: "user", text: current, complete: true }, { role: "assistant", text: "", complete: false }] }));
    const active = () => this.requests.get(id) === request && !request.controller.signal.aborted;
    try {
      const final = await this.adapter({ anchor: session.anchor, history: previous.filter((message) => message.complete),
        question: current, threadId: id, requestId: request.id, signal: request.controller.signal,
        onDelta: (delta) => {
          if (active()) this.update(id, (item) => ({ ...item, messages: item.messages.map((message, i) =>
            i === item.messages.length - 1 ? { ...message, text: message.text + delta } : message) }));
        } });
      if (active()) this.update(id, (item) => ({ ...item, status: "ready", messages: item.messages.map((message, i) =>
        i === item.messages.length - 1 ? { ...message, text: final, complete: true } : message) }));
    } catch {
      if (active()) this.update(id, (item) => ({ ...item, status: "error", error: "The reply could not finish. Retry this question.",
        messages: item.messages.map((message, i) => i === item.messages.length - 1 ? { ...message, complete: false } : message) }));
    } finally {
      if (this.requests.get(id) === request) this.requests.delete(id);
    }
  }
  stop(id: string) {
    const request = this.requests.get(id);
    this.requests.delete(id); // Invalidate before abort, including uncooperative adapters.
    request?.controller.abort();
    if (request) this.update(id, (item) => ({ ...item, status: "error", error: "Reply stopped. Retry this question to continue." }));
  }
  remove(id: string) {
    this.stop(id);
    const next = { ...this.sessions }; delete next[id]; this.sessions = next;
    this.listeners.forEach((listener) => listener());
  }
  dispose() { for (const id of this.requests.keys()) this.stop(id); }
}
