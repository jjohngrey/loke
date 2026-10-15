import type { MultipleChoiceElement, RunEvent, RunOutcome } from "@loke/contracts";

export type RuntimeDisplay = {
  runId?: string;
  text: string;
  elements: MultipleChoiceElement[];
  sequence: number;
  progress: string;
  outcome?: RunOutcome;
};

export function emptyDisplay(): RuntimeDisplay {
  return { text: "", elements: [], sequence: -1, progress: "Connecting" };
}

export function applyRunEvent(display: RuntimeDisplay, event: RunEvent): RuntimeDisplay {
  if ((display.runId && display.runId !== event.run_id) || event.sequence <= display.sequence)
    return display;
  const elements = new Map(display.elements.map((element) => [element.element_id, element]));
  if (event.element) elements.set(event.element.element_id, event.element);
  for (const element of event.outcome?.elements || []) elements.set(element.element_id, element);
  return {
    ...display,
    runId: event.run_id,
    sequence: event.sequence,
    text: event.outcome ? event.outcome.text :
      event.type === "message_delta" ? display.text + (event.message || "") : display.text,
    elements: [...elements.values()],
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
