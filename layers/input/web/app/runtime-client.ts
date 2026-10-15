import type { MultipleChoiceElement, RunEvent, RunOutcome } from "@loke/contracts";

export type RuntimeBlock =
  | { kind: "text"; id: string; text: string }
  | { kind: "element"; id: string; element: MultipleChoiceElement };

export type RuntimeDisplay = {
  runId?: string;
  text: string;
  blocks: RuntimeBlock[];
  sequence: number;
  progress: string;
  outcome?: RunOutcome;
};

export function emptyDisplay(): RuntimeDisplay {
  return { text: "", blocks: [], sequence: -1, progress: "Connecting" };
}

function appendText(blocks: RuntimeBlock[], text: string, sequence: number) {
  if (!text) return blocks;
  const last = blocks[blocks.length - 1];
  if (last?.kind === "text") {
    return [...blocks.slice(0, -1), { ...last, text: last.text + text }];
  }
  return [...blocks, { kind: "text" as const, id: `text-${sequence}`, text }];
}

function addElement(blocks: RuntimeBlock[], element: MultipleChoiceElement) {
  const index = blocks.findIndex((block) => block.kind === "element" && block.id === element.element_id);
  if (index >= 0) {
    return blocks.map((block, blockIndex) => blockIndex === index
      ? { kind: "element" as const, id: element.element_id, element }
      : block);
  }
  return [...blocks, { kind: "element" as const, id: element.element_id, element }];
}

export function applyRunEvent(display: RuntimeDisplay, event: RunEvent): RuntimeDisplay {
  if ((display.runId && display.runId !== event.run_id) || event.sequence <= display.sequence)
    return display;
  let blocks = display.blocks;
  let text = display.text;
  if (event.type === "message_delta" && event.message) {
    text += event.message;
    blocks = appendText(blocks, event.message, event.sequence);
  }
  if (event.element) blocks = addElement(blocks, event.element);
  for (const element of event.outcome?.elements || []) blocks = addElement(blocks, element);
  if (event.outcome && event.outcome.text !== text) {
    const finalText = event.outcome.text;
    if (finalText.startsWith(text)) {
      blocks = appendText(blocks, finalText.slice(text.length), event.sequence);
    } else {
      let replaced = false;
      blocks = blocks.map<RuntimeBlock>((block) => {
        if (block.kind !== "text") return block;
        if (replaced) return { ...block, text: "" };
        replaced = true;
        return { ...block, text: finalText };
      }).filter((block) => block.kind !== "text" || block.text.length > 0);
      if (!replaced) blocks = appendText(blocks, finalText, event.sequence);
    }
    text = finalText;
  }
  return {
    ...display,
    runId: event.run_id,
    sequence: event.sequence,
    text,
    blocks,
    progress: event.type === "progress" ? event.message || "Working" : display.progress,
    outcome: event.outcome || display.outcome,
  };
}

export async function readRunEvents(response: Response, receive: (event: RunEvent) => void) {
  if (!response.body) throw new Error("The response stream is unavailable.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) if (line.trim()) receive(JSON.parse(line) as RunEvent);
      if (buffer.length > 100000) throw new Error("The response event exceeds its size limit.");
      if (done) {
        if (buffer.trim()) throw new Error("The response stream ended during an event.");
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
