import assert from "node:assert/strict";
import { test } from "node:test";
import { intelligenceThreadAdapter } from "../layers/input/web/app/side-thread-client.ts";

const anchor = { chatId: "chat", messageId: "message", sourceMarkdown: "$E=mc^2$", selectedText: "mc2", startOffset: 2, endOffset: 5,
  streamVersion: "loke-rendered-v1", mainHistory: [{ role: "assistant", text: "$E=mc^2$" }] };
const input = (onDelta = () => {}) => ({ anchor, threadId: "thread", history: [{ role: "user", text: "First question", complete: true }, { role: "assistant", text: "First reply", complete: true }],
  question: "Latest question", requestId: "request", signal: new AbortController().signal, onDelta });
const event = (type, text, extra = {}) => JSON.stringify({ thread_id: "thread", request_id: "request", type, text, ...extra }) + "\n";

test("Intelligence adapter sends original source, main path, own history and current question exactly once", async () => {
  const original = globalThis.fetch; const deltas = []; let payload;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "/api/backend/side-threads/reply"); payload = JSON.parse(init.body);
    const bytes = new TextEncoder().encode(event("delta", "选择") + event("completed", "选择 final"));
    return new Response(new ReadableStream({ start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close();
    } }));
  };
  try {
    const final = await intelligenceThreadAdapter("generation")(input((text) => deltas.push(text)));
    assert.equal(final, "选择 final"); assert.deepEqual(deltas, ["选择"]);
    assert.equal(payload.anchor.source_markdown, "$E=mc^2$"); assert.equal(payload.anchor.selected_text, "mc2");
    assert.equal(payload.main_history[0].text, "$E=mc^2$");
    assert.deepEqual(payload.history.map((m) => m.text), ["First question", "First reply"]);
    assert.equal(payload.question, "Latest question");
    assert.equal(payload.history.some((m) => m.text === payload.question), false);
    assert.equal(payload.thread_id, "thread"); assert.equal(payload.generation_id, "generation");
  } finally { globalThis.fetch = original; }
});

for (const [name, body] of [
  ["missing terminal event", event("delta", "Partial")],
  ["truncated JSON", event("delta", "Partial") + '{"type":'],
  ["foreign request", event("completed", "Wrong", { request_id: "other" })],
  ["error terminal", event("error", "Failure")],
  ["unknown event", event("unexpected", "Bad")],
]) test(`Intelligence adapter rejects ${name}`, async () => {
  const original = globalThis.fetch; globalThis.fetch = async () => new Response(body);
  try { await assert.rejects(intelligenceThreadAdapter("generation")(input())); }
  finally { globalThis.fetch = original; }
});

test("aborted reads cannot publish a late delta", async () => {
  const original = globalThis.fetch; const controller = new AbortController(); const deltas = [];
  globalThis.fetch = async () => { controller.abort(); return new Response(event("delta", "Late") + event("completed", "Late")); };
  try {
    await assert.rejects(intelligenceThreadAdapter("generation")({ ...input((text) => deltas.push(text)), signal: controller.signal }), /Stopped/);
    assert.deepEqual(deltas, []);
  } finally { globalThis.fetch = original; }
});
