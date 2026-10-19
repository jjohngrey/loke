import type { SideThreadEvent, SideThreadRequest, SideThreadTurn } from "@loke/contracts";
import type { ThreadAdapter } from "./side-thread-store";

function boundedTurns(turns: { role: "user" | "assistant"; text: string }[]) {
  const result: SideThreadTurn[] = [];
  let used = 0;
  for (const turn of [...turns].reverse()) {
    if (result.length === 100 || used + turn.text.length > 80000 || turn.text.length > 24000) break;
    if (!turn.text) continue;
    result.push({ role: turn.role, text: turn.text }); used += turn.text.length;
  }
  return { turns: result.reverse(), truncated: result.length !== turns.length };
}

export function intelligenceThreadAdapter(generationId: string): ThreadAdapter {
  return async ({ anchor, history, question, threadId, requestId, signal, onDelta }) => {
    const main = boundedTurns(anchor.mainHistory), side = boundedTurns(history);
    const payload: SideThreadRequest = {
      generation_id: generationId, thread_id: threadId,
      request_id: requestId,
      anchor: { chat_id: anchor.chatId, message_id: anchor.messageId, source_markdown: anchor.sourceMarkdown,
        selected_text: anchor.selectedText, start_offset: anchor.startOffset, end_offset: anchor.endOffset, stream_version: anchor.streamVersion },
      main_history: main.turns, history: side.turns, question,
      main_history_truncated: main.truncated, history_truncated: side.truncated,
    };
    const response = await fetch("/api/backend/side-threads/reply", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload), signal });
    if (!response.ok || !response.body) throw new Error("The side reply is unavailable.");
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "", final: string | null = null;
    function receive(line: string) {
      if (!line.trim()) return;
      const event = JSON.parse(line) as SideThreadEvent;
      if (event.request_id !== requestId || event.thread_id !== payload.thread_id || typeof event.text !== "string" || final !== null)
        throw new Error("Unexpected side reply event.");
      if (event.type === "error") throw new Error("The side reply could not finish.");
      if (event.type === "delta") onDelta(event.text);
      else if (event.type === "completed" && event.text.trim()) final = event.text;
      else throw new Error("Unknown side reply event.");
    }
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (signal.aborted) throw new DOMException("Stopped", "AbortError");
        buffer += decoder.decode(value, { stream: !done });
        if (buffer.length > 100000) throw new Error("The side reply exceeded its limit.");
        const lines = buffer.split("\n"); buffer = lines.pop() || "";
        for (const line of lines) receive(line);
        if (done) {
          if (buffer.trim() || final === null) throw new Error("The side reply ended early.");
          return final;
        }
      }
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  };
}
