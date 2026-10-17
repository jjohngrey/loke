import type { RunEvent, RunOutcome } from "@loke/contracts";

export type RuntimeBlock = RunOutcome["blocks"][number];

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

/** Show a completed prefix plus its first streaming text block. */
export function visibleBlocks(blocks: RuntimeBlock[]): RuntimeBlock[] {
  const visible: RuntimeBlock[] = [];
  for (const block of blocks) {
    if (block.kind === "tool" && block.state === "pending") break;
    visible.push(block);
    if (block.kind === "text" && block.state === "streaming") break;
  }
  return visible;
}

export function applyRunEvent(display: RuntimeDisplay, event: RunEvent): RuntimeDisplay {
  if (display.outcome || (display.runId && display.runId !== event.run_id) ||
      event.sequence <= display.sequence) return display;
  if (event.type !== "outcome" && event.sequence !== display.sequence + 1)
    throw new Error("The response stream is missing an event. Retry to reconnect.");

  let blocks = display.blocks;
  if (event.type === "block_start" && event.block) {
    if (blocks.some((block) => block.block_id === event.block?.block_id))
      throw new Error("The response stream repeated a block. Retry to reconnect.");
    blocks = [...blocks, event.block];
  }
  if (event.type === "text_delta") {
    const index = blocks.findIndex((block) => block.block_id === event.block_id);
    const block = blocks[index];
    if (!block || block.kind !== "text" || block.state !== "streaming")
      throw new Error("The response stream contains unexpected text. Retry to reconnect.");
    blocks = blocks.map((item, itemIndex) => itemIndex === index
      ? { ...block, text: block.text + (event.message || "") } : item);
  }
  if ((event.type === "block_end" || event.type === "tool_result") && event.block) {
    const updated = event.block;
    const index = blocks.findIndex((block) => block.block_id === updated.block_id);
    if (index < 0 || blocks[index].kind !== updated.kind)
      throw new Error("The response stream contains an unknown block. Retry to reconnect.");
    blocks = blocks.map((block, blockIndex) => blockIndex === index ? updated : block);
  }
  // Ordered snapshots, rather than flat text and element arrays, are authoritative on replay.
  if (event.outcome) blocks = event.outcome.blocks;
  return {
    ...display,
    runId: event.run_id,
    sequence: event.sequence,
    text: event.outcome?.text ?? blocks.filter((block) => block.kind === "text")
      .map((block) => block.text).join("\n"),
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
