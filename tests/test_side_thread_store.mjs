import assert from "node:assert/strict";
import { test } from "node:test";
import { SideThreadStore } from "../layers/input/web/app/side-thread-store.ts";

const anchor = { chatId: "chat-a", messageId: "source", sourceMarkdown: "$a^2$", selectedText: "a2", startOffset: 0, endOffset: 2,
  streamVersion: "loke-rendered-v1", renderedText: "a2", mainHistory: [{ role: "assistant", text: "$a^2$" }] };
function deferredAdapter() {
  const calls = [];
  const adapter = (input) => new Promise((resolve, reject) => calls.push({ input, resolve, reject }));
  return { calls, adapter };
}

test("threads stream independently, final replaces deltas, and follow-up history excludes its question", async () => {
  const { calls, adapter } = deferredAdapter();
  const store = new SideThreadStore(adapter);
  const a = store.create(anchor, "Why squared?");
  const b = store.create({ ...anchor, chatId: "chat-b" }, "Explain b");
  const first = store.send(a), second = store.send(b);
  await store.send(a, "Duplicate");
  assert.equal(calls.length, 2);
  calls[1].input.onDelta("B reply"); calls[0].input.onDelta("A partial");
  assert.equal(store.snapshot()[a].messages.at(-1).text, "A partial");
  assert.equal(store.snapshot()[b].messages.at(-1).text, "B reply");
  calls[0].resolve("A final"); calls[1].resolve("B final"); await Promise.all([first, second]);
  calls[0].input.onDelta(" late");
  assert.equal(store.snapshot()[a].messages.at(-1).text, "A final");
  store.draft(b, "Keep B draft");
  const followup = store.send(a, "What about units?");
  assert.deepEqual(calls[2].input.history.map((m) => m.text), ["Why squared?", "A final"]);
  assert.equal(calls[2].input.question, "What about units?");
  assert.equal(calls[2].input.anchor.sourceMarkdown, "$a^2$");
  calls[2].resolve("Units"); await followup;
  assert.equal(store.snapshot()[b].draft, "Keep B draft");
});

test("failure and retry preserve one user turn and ignore late results after Stop", async () => {
  const { calls, adapter } = deferredAdapter(); const store = new SideThreadStore(adapter);
  const id = store.create(anchor, "Explain this"); const first = store.send(id);
  calls[0].input.onDelta("partial"); calls[0].reject(new Error("failure")); await first;
  assert.equal(store.snapshot()[id].status, "error");
  await store.send(id, "Cannot bypass retry"); assert.equal(calls.length, 1);
  const retry = store.send(id, undefined, true);
  assert.equal(store.snapshot()[id].messages.filter((m) => m.role === "user").length, 1);
  assert.equal(calls[1].input.question, "Explain this");
  assert.deepEqual(calls[1].input.history, []);
  store.stop(id); assert.equal(calls[1].input.signal.aborted, true);
  const replacement = store.send(id, undefined, true);
  calls[1].input.onDelta("stale"); calls[1].resolve("stale final"); await retry;
  assert.equal(store.snapshot()[id].status, "loading");
  assert.equal(store.snapshot()[id].messages.at(-1).text, "");
  calls[2].resolve("Replacement"); await replacement;
  assert.equal(store.snapshot()[id].messages.at(-1).text, "Replacement");
  assert.equal(store.snapshot()[id].messages.length, 2);
});

test("source invalidation and disposal abort requests without reviving removed sessions", async () => {
  const { calls, adapter } = deferredAdapter(); const store = new SideThreadStore(adapter);
  const id = store.create(anchor, "Question"); const first = store.send(id);
  store.remove(id); calls[0].input.onDelta("stale"); calls[0].resolve("stale"); await first;
  assert.equal(store.snapshot()[id], undefined);
  const next = store.create(anchor, "Other"); const request = store.send(next);
  store.dispose(); assert.equal(calls[1].input.signal.aborted, true);
  calls[1].resolve("stale"); await request;
  assert.equal(store.snapshot()[next].status, "error");
});
