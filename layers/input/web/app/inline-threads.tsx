"use client";

import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChatMarkdown } from "./chat-markdown";
import { buildTextIndex, captureRange, restoreRanges, SELECTION_VERSION, visibleRects } from "./selection-index";
import { fakeThreadAdapter, SideThreadStore, type SelectionAnchor, type SourceMessage, type ThreadAdapter, type ThreadSession } from "./side-thread-store";

type Pending = { anchor: SelectionAnchor; left: number; top: number };
function contentRoot(node: Node) {
  return (node instanceof Element ? node : node.parentElement)?.closest<HTMLElement>("[data-message-content]");
}

export function InlineThreads({ chatId, sources, children, adapter = fakeThreadAdapter }: {
  chatId: string | null; sources: SourceMessage[]; children: ReactNode; adapter?: ThreadAdapter;
}) {
  const [store] = useState(() => new SideThreadStore(adapter));
  const sessions = useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [question, setQuestion] = useState("");
  const [width, setWidth] = useState(420);
  const [narrow, setNarrow] = useState(false);
  const [fallback, setFallback] = useState<{ rect: DOMRect; active: boolean }[]>([]);
  const layout = useRef<HTMLDivElement>(null);
  const popover = useRef<HTMLFormElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const popoverEdited = useRef(false);
  const focusFrame = useRef(0);
  const panel = useRef<HTMLElement>(null);
  const selectionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hitRanges = useRef<{ id: string; root: HTMLElement; ranges: Range[] }[]>([]);
  const dragStart = useRef({ x: 0, y: 0 });
  const dragged = useRef(false);
  const active = activeId ? sessions[activeId] : undefined;
  const visible = Object.values(sessions).filter((session) => session.anchor.chatId === chatId);
  const latest = useRef({ chatId, sources }); latest.current = { chatId, sources };

  function rootFor(anchor: SelectionAnchor) {
    return Array.from(layout.current?.querySelectorAll<HTMLElement>("[data-message-content]") || [])
      .find((root) => root.dataset.messageId === anchor.messageId);
  }
  function returnFocus(anchor?: SelectionAnchor) {
    cancelAnimationFrame(focusFrame.current);
    focusFrame.current = requestAnimationFrame(() => {
      const root = anchor && rootFor(anchor);
      (root || layout.current?.querySelector<HTMLElement>("#message-input"))?.focus({ preventScroll: true });
    });
  }
  function dismiss() { setPending(null); setQuestion(""); }
  function close() { setActiveId(null); returnFocus(active?.anchor); }
  function open(id: string) { dismiss(); setActiveId(id); }
  function start(send: boolean) {
    if (!pending || !question.trim()) return;
    const id = store.create(pending.anchor, question);
    open(id);
    if (send) void store.send(id);
  }

  useEffect(() => {
    const media = matchMedia("(max-width: 767px)");
    const update = () => setNarrow(media.matches); update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => { setActiveId(null); dismiss(); }, [chatId]);
  useEffect(() => () => { store.dispose(); cancelAnimationFrame(focusFrame.current); if (selectionTimer.current) clearTimeout(selectionTimer.current); }, [store]);
  useEffect(() => {
    for (const session of Object.values(store.snapshot())) {
      if (session.anchor.chatId !== chatId) continue;
      const source = sources.find((source) => source.id === session.anchor.messageId);
      if (!source || source.markdown !== session.anchor.sourceMarkdown) store.remove(session.id);
    }
    if (pending && !sources.some((source) => source.id === pending.anchor.messageId && source.markdown === pending.anchor.sourceMarkdown)) dismiss();
  }, [chatId, sources, store, pending]);
  useEffect(() => {
    if (pending) input.current?.focus({ preventScroll: true });
  }, [pending?.anchor]);
  useEffect(() => {
    if (!active) return;
    panel.current?.querySelector<HTMLTextAreaElement>("textarea")?.focus({ preventScroll: true });
  }, [active?.id]);
  useEffect(() => {
    const main = layout.current?.querySelector<HTMLElement>(".conversation");
    if (main) main.inert = !!active && narrow;
    return () => { if (main) main.inert = false; };
  }, [!!active, narrow]);

  useEffect(() => {
    const pointer = (event: PointerEvent) => {
      if (pending && !popover.current?.contains(event.target as Node)) dismiss();
    };
    const keyboard = (event: KeyboardEvent) => {
      if (event.ctrlKey && !event.metaKey && event.key.toLowerCase() === "l") {
        if (pending) { event.preventDefault(); start(false); }
        else if (active) { event.preventDefault(); close(); }
      }
      if (event.key === "Escape") {
        if (pending) { dismiss(); returnFocus(pending.anchor); }
        else if (active) close();
      }
      if (event.key === "Tab" && active && narrow && panel.current) {
        const items = [...panel.current.querySelectorAll<HTMLElement>("button:not(:disabled), textarea, input")];
        const first = items[0], last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("pointerdown", pointer);
    document.addEventListener("keydown", keyboard);
    return () => { document.removeEventListener("pointerdown", pointer); document.removeEventListener("keydown", keyboard); };
  });

  // Native highlights paint each text fragment without wrapping syntax or math nodes.
  // The fallback uses clipped leaf rectangles, never a whole equation's bounding box.
  useLayoutEffect(() => {
    const host = layout.current;
    if (!host) return;
    let frame = 0;
    let alive = true;
    const native = typeof Highlight !== "undefined" && !!CSS.highlights;
    const measure = () => {
      frame = 0;
      const ordinary: Range[] = [], selected: Range[] = [], preview: Range[] = [];
      const hits: typeof hitRanges.current = [];
      const painted: { anchor: SelectionAnchor; id: string; active: boolean }[] = [];
      const ordered = [...visible].sort((a, b) => Number(b.id === activeId) - Number(a.id === activeId)
        || a.anchor.startOffset - b.anchor.startOffset || b.anchor.endOffset - a.anchor.endOffset);
      if (pending) painted.push({ anchor: pending.anchor, id: "pending", active: true });
      for (const session of ordered) {
        const a = session.anchor;
        if (painted.some(({ anchor: b }) => a.messageId === b.messageId && a.startOffset < b.endOffset && b.startOffset < a.endOffset)) continue;
        painted.push({ anchor: a, id: session.id, active: session.id === activeId });
      }
      const rectangles: typeof fallback = [];
      for (const item of painted) {
        const root = rootFor(item.anchor);
        if (!root || item.anchor.streamVersion !== SELECTION_VERSION) continue;
        const index = buildTextIndex(root);
        if (index.text !== item.anchor.renderedText) {
          if (item.id === "pending") setPending(null); else store.remove(item.id);
          continue;
        }
        const ranges = restoreRanges(index, item.anchor.startOffset, item.anchor.endOffset);
        (item.id === "pending" ? preview : item.active ? selected : ordinary).push(...ranges);
        hits.push({ id: item.id, root, ranges });
        if (!native) {
          const seen = new Set<string>();
          for (const range of ranges) for (const rect of visibleRects(range, root)) {
            const key = [rect.x, rect.y, rect.width, rect.height].map(Math.round).join(":");
            if (!seen.has(key)) { seen.add(key); rectangles.push({ rect, active: item.active }); }
          }
        }
        if (item.id === "pending") {
          const rect = ranges.flatMap((range) => visibleRects(range, root))[0];
          if (rect) {
            const bounds = host.getBoundingClientRect();
            const popWidth = Math.min(360, bounds.width - 16);
            const left = Math.max(bounds.left + 8, Math.min(rect.left, bounds.right - popWidth - 8));
            const height = popover.current?.offsetHeight || 156;
            const top = rect.top - height - 8 >= bounds.top ? rect.top - height - 8 : Math.min(rect.bottom + 8, window.innerHeight - height - 8);
            setPending((old) => old && (old.left !== left || old.top !== top) ? { ...old, left, top } : old);
          }
        }
      }
      hitRanges.current = hits;
      if (native) {
        CSS.highlights.set("loke-side", new Highlight(...ordinary));
        CSS.highlights.set("loke-side-active", new Highlight(...selected));
        CSS.highlights.set("loke-side-preview", new Highlight(...preview));
      } else setFallback(rectangles);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    measure();
    const observer = new ResizeObserver(schedule); observer.observe(host);
    for (const root of host.querySelectorAll("[data-message-content]")) observer.observe(root);
    window.addEventListener("resize", schedule);
    document.addEventListener("scroll", schedule, true);
    void document.fonts.ready.then(() => { if (alive) schedule(); });
    return () => {
      alive = false; cancelAnimationFrame(frame); observer.disconnect();
      window.removeEventListener("resize", schedule); document.removeEventListener("scroll", schedule, true);
      if (native) for (const name of ["loke-side", "loke-side-active", "loke-side-preview"]) CSS.highlights.delete(name);
    };
  }, [sessions, chatId, activeId, pending?.anchor, sources]);

  function resolveSelection() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    const root = contentRoot(range.startContainer);
    if (!root || root !== contentRoot(range.endContainer) || !layout.current?.contains(root)) return;
    const source = latest.current.sources.find((item) => item.id === root.dataset.messageId);
    if (!source || !latest.current.chatId) return;
    const captured = captureRange(root, range);
    if (!captured || captured.selectedText.length > 20000) return;
    const rect = [...range.getClientRects()].find((rect) => rect.width > .5 && rect.height > .5) || range.getBoundingClientRect();
    const anchor: SelectionAnchor = { ...captured, chatId: latest.current.chatId, messageId: source.id,
      sourceMarkdown: source.markdown, mainHistory: source.history, renderedText: buildTextIndex(root).text };
    setPending({ anchor, left: Math.max(8, Math.min(rect.left, window.innerWidth - 368)), top: rect.bottom + 8 });
    setQuestion(""); popoverEdited.current = false; selection.removeAllRanges();
  }
  function scheduleSelection() {
    if (selectionTimer.current) clearTimeout(selectionTimer.current);
    selectionTimer.current = setTimeout(resolveSelection, 0);
  }
  function showSource(anchor: SelectionAnchor) {
    const root = rootFor(anchor); if (!root) return;
    if (narrow) setActiveId(null);
    const ranges = restoreRanges(buildTextIndex(root), anchor.startOffset, anchor.endOffset);
    const element = ranges[0]?.startContainer.parentElement || root;
    element.scrollIntoView({ block: "center", inline: "nearest" });
    returnFocus(anchor);
  }

  return (
    <div className={`thread-layout ${active ? "has-side-thread" : ""}`} ref={layout}
      style={{ "--side-thread-width": `${width}px` } as React.CSSProperties}
      onPointerDown={(event) => { dragStart.current = { x: event.clientX, y: event.clientY }; dragged.current = false; }}
      onPointerMove={(event) => { if (event.buttons && Math.hypot(event.clientX - dragStart.current.x, event.clientY - dragStart.current.y) > 4) dragged.current = true; }}
      onPointerUp={scheduleSelection}
      onKeyUp={(event) => { if (event.key === "Shift") scheduleSelection(); }}
      onClick={(event) => {
        if (dragged.current || !window.getSelection()?.isCollapsed || (event.target as Element).closest("button, input, textarea, a, [data-selection-exclude]")) return;
        for (const hit of hitRanges.current) {
          if (hit.id === "pending") continue;
          if (hit.ranges.some((range) => visibleRects(range, hit.root).some((rect) => event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom))) { open(hit.id); break; }
        }
      }}>
      {children}
      {visible.length > 0 && <nav className="side-thread-links" aria-label="Side chats"><details><summary>Side chats ({visible.length})</summary>
        {visible.map((session, i) => <button key={session.id} onClick={() => open(session.id)} aria-current={activeId === session.id ? "true" : undefined}>
          Open side chat {i + 1}: {session.anchor.selectedText.slice(0, 44)}
        </button>)}
      </details></nav>}
      {active && <aside className="side-thread-panel" ref={panel} aria-label="Side chat" role={narrow ? "dialog" : undefined} aria-modal={narrow || undefined}>
        <header><strong>Side chat</strong><button onClick={close} aria-label="Close side chat">Close</button></header>
        <div className="side-thread-source"><span>Selected passage</span><blockquote>{active.anchor.selectedText}</blockquote>
          <button onClick={() => showSource(active.anchor)}>Show in chat</button>
        </div>
        {!narrow && <label className="side-thread-width">Panel width<input aria-label="Side chat width" type="range" min="280" max="640" value={width} onChange={(event) => setWidth(Number(event.target.value))} /></label>}
        <ThreadConversation session={active} store={store} />
      </aside>}
      {pending && createPortal(<form ref={popover} className="selection-popover" aria-label="Ask about selected passage"
        style={{ left: pending.left, top: pending.top }} onSubmit={(event) => { event.preventDefault(); start(true); }}>
        <blockquote>{pending.anchor.selectedText}</blockquote>
        <label className="sr-only" htmlFor="passage-question">Ask about this passage</label>
        <div><input id="passage-question" ref={input} placeholder="Ask about this…" value={question} maxLength={8000}
          onChange={(event) => { popoverEdited.current = true; setQuestion(event.target.value); }}
          onCopy={(event) => {
            if (!popoverEdited.current && event.currentTarget.selectionStart === event.currentTarget.selectionEnd) {
              event.preventDefault(); event.clipboardData.setData("text/plain", pending.anchor.selectedText);
            }
          }} /><button type="submit" disabled={!question.trim()}>Ask</button></div>
        <button className="selection-dismiss" type="button" onClick={() => { dismiss(); returnFocus(pending.anchor); }}>Dismiss</button>
      </form>, document.body)}
      {fallback.length > 0 && createPortal(<div className="selection-fallback" aria-hidden="true" data-selection-exclude>
        {fallback.map(({ rect, active }, i) => <i key={i} className={active ? "active" : ""} style={{ left: rect.x, top: rect.y, width: rect.width, height: rect.height }} />)}
      </div>, document.body)}
    </div>
  );
}

function ThreadConversation({ session, store }: { session: ThreadSession; store: SideThreadStore }) {
  const scroller = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useLayoutEffect(() => { follow.current = true; }, [session.id]);
  useLayoutEffect(() => {
    if (follow.current && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [session.messages, session.id]);
  return <>
    <div ref={scroller} className="side-thread-messages" role="log" aria-label="Side chat messages" aria-live="polite"
      onScroll={() => { const el = scroller.current!; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48; }}>
      {!session.messages.length && <p>Ask a question about the selected passage.</p>}
      {session.messages.map((message, i) => <article key={`${session.id}-${i}`} className={`side-thread-message ${message.role}`}>
        <span>{message.role === "user" ? "You" : "Loke"}</span>
        {message.role === "assistant" ? <ChatMarkdown text={message.text} streaming={!message.complete && session.status === "loading"} /> : <p>{message.text}</p>}
        {message.role === "assistant" && !message.text && session.status === "loading" && <p role="status">Thinking…</p>}
      </article>)}
      {session.error && <div role="alert">{session.error}<button onClick={() => void store.send(session.id, undefined, true)}>Retry reply</button></div>}
    </div>
    <form className="side-thread-composer" onSubmit={(event) => { event.preventDefault(); void store.send(session.id); }}>
      <label className="sr-only" htmlFor="side-thread-draft">Side chat question</label>
      <textarea id="side-thread-draft" value={session.draft} maxLength={8000} placeholder="Follow up on this passage…" rows={3}
        onChange={(event) => store.draft(session.id, event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault(); if (session.status === "ready") void store.send(session.id);
          }
        }} />
      {session.status === "loading" ? <button type="button" onClick={() => store.stop(session.id)}>Stop reply</button>
        : <button type="submit" disabled={!session.draft.trim() || session.status === "error"}>Send question</button>}
    </form>
  </>;
}
