import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import * as runtimeClient from "../layers/input/web/app/runtime-client.ts";
const { applyRunEvent, emptyDisplay, readRunEvents } = runtimeClient;

const element = {
  type: "multiple_choice", element_id: "element-1", question: "Choose?",
  choices: [{ id: "a", text: "A" }, { id: "b", text: "B" }, { id: "c", text: "C" }],
};
const event = (sequence, type, fields = {}) => ({
  run_id: "run-1", request_id: "request-1", session_epoch: 0, sequence, type, ...fields,
});

test("progress replay and final outcomes merge one card by run/element identity", () => {
  const events = [event(0, "progress", { message: "Thinking" }),
    event(1, "element", { element }), event(2, "message_delta", { message: "Choose." }),
    event(3, "outcome", { outcome: { status: "completed", text: "Final text.", elements: [element] } })];
  let state = events.reduce(applyRunEvent, emptyDisplay());
  state = events.reduce(applyRunEvent, state);
  assert.equal(state.text, "Final text.");
  assert.equal(state.blocks.filter((block) => block.kind === "element").length, 1);
  assert.equal(state.sequence, 3);
  assert.equal(applyRunEvent(state, { ...event(4, "element", { element }), run_id: "another" }), state);
});

test("follow-up choices wait for successful completion after all response text", () => {
  let state = applyRunEvent(emptyDisplay(), event(0, "element", {
    element: { ...element, presentation: "after_response" },
  }));
  assert.deepEqual(state.blocks, []);
  state = applyRunEvent(state, event(1, "message_delta", { message: "An overview" }));
  assert.deepEqual(state.blocks.map((block) => block.kind), ["text"]);
  assert.equal(state.blocks[0].text, "An overview");
  state = applyRunEvent(state, event(2, "outcome", { outcome: {
    status: "completed", text: "An overview with final details.",
    elements: [{ ...element, presentation: "after_response" }],
  } }));
  assert.deepEqual(state.blocks.map((block) => block.kind), ["text", "element"]);
  assert.equal(state.blocks[0].text, "An overview with final details.");
  assert.equal(state.blocks[1].id, element.element_id);
});

test("choices without presentation metadata default to after the response", () => {
  let state = applyRunEvent(emptyDisplay(), event(0, "element", { element }));
  assert.deepEqual(state.blocks, []);
  state = applyRunEvent(state, event(1, "outcome", { outcome: {
    status: "completed", text: "Context first.", elements: [element],
  } }));
  assert.deepEqual(state.blocks.map((block) => block.kind), ["text", "element"]);
});

test("inline choices keep their position between streamed text blocks", () => {
  let state = applyRunEvent(emptyDisplay(), event(0, "message_delta", { message: "Before." }));
  const inline = { ...element, presentation: "inline" };
  state = applyRunEvent(state, event(1, "element", { element: inline }));
  assert.deepEqual(state.blocks.map((block) => block.kind), ["text", "element"]);
  state = applyRunEvent(state, event(2, "message_delta", { message: "After." }));
  state = applyRunEvent(state, event(3, "outcome", { outcome: {
    status: "completed", text: "Before.After.", elements: [inline],
  } }));
  assert.deepEqual(state.blocks.map((block) => block.kind), ["text", "element", "text"]);
});

test("outcome-only replay puts follow-up choices after authoritative text", () => {
  const final = event(5, "outcome", { outcome: {
    status: "completed", text: "The complete explanation.", elements: [element],
  } });
  const state = applyRunEvent(emptyDisplay(), final);
  assert.deepEqual(state.blocks.map((block) => block.kind), ["text", "element"]);
  assert.equal(applyRunEvent(state, final), state);
});

test("pending choices update without duplication and remain after corrected final text", () => {
  let state = applyRunEvent(emptyDisplay(), event(0, "message_delta", { message: "Draft." }));
  state = applyRunEvent(state, event(1, "element", { element }));
  const updated = { ...element, question: "Updated question?" };
  state = applyRunEvent(state, event(2, "element", { element: updated }));
  const second = { ...element, element_id: "element-2" };
  state = applyRunEvent(state, event(3, "element", { element: second }));
  state = applyRunEvent(state, event(4, "outcome", { outcome: {
    status: "completed", text: "Corrected explanation.", elements: [updated, second],
  } }));
  assert.deepEqual(state.blocks.map((block) => block.kind), ["text", "element", "element"]);
  assert.equal(state.blocks[0].text, "Corrected explanation.");
  assert.equal(state.blocks[1].element.question, "Updated question?");
  assert.equal(state.blocks[2].id, second.element_id);
});

for (const status of ["failed", "cancelled"]) {
  test(`${status} responses discard pending choices while preserving text`, () => {
    let state = applyRunEvent(emptyDisplay(), event(0, "element", { element }));
    state = applyRunEvent(state, event(1, "message_delta", { message: "Partial explanation." }));
    state = applyRunEvent(state, event(2, "outcome", { outcome: {
      status, text: "Partial explanation.", notice: "Response stopped.", elements: [element],
    } }));
    assert.deepEqual(state.blocks.map((block) => block.kind), ["text"]);
    assert.equal(state.text, "Partial explanation.");
    assert.equal(state.outcome.notice, "Response stopped.");
    assert.deepEqual(state.pendingElements, []);
  });
}

test("streaming proxy survives its former deadline and still propagates client cancellation", async () => {
  const require = createRequire(import.meta.url);
  const ts = require("typescript");
  const source = readFileSync(new URL("../layers/input/web/app/api/backend/[...path]/route.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const exported = {};
  new Function("exports", outputText)(exported);
  const originalFetch = globalThis.fetch;
  const originalTimeout = AbortSignal.timeout;
  const timers = [];
  const signals = [];
  AbortSignal.timeout = (milliseconds) => {
    const controller = new AbortController();
    timers.push({ milliseconds, controller });
    return controller.signal;
  };
  globalThis.fetch = async (_url, options) => {
    signals.push(options.signal);
    return new Response(new ReadableStream({ start(controller) {
      options.signal.addEventListener("abort", () => controller.error(new Error("Aborted")));
      // Advance all proxy deadline timers while the upstream response is active.
      for (const timer of timers) timer.controller.abort();
      if (!options.signal.aborted) {
        controller.enqueue(new TextEncoder().encode("continued response\n"));
        controller.close();
      }
    } }), { headers: { "content-type": "application/x-ndjson" } });
  };
  try {
    const client = new AbortController();
    const response = await exported.POST(new Request("http://127.0.0.1/api/backend/runtime/run", {
      method: "POST", body: "{}", signal: client.signal,
    }), { params: Promise.resolve({ path: ["runtime", "run"] }) });
    assert.equal(await response.text(), "continued response\n");
    assert.equal(timers.length, 0);
    client.abort();
    assert.equal(signals[0].aborted, true);
    const view = await exported.GET(new Request("http://127.0.0.1/api/backend/view"), {
      params: Promise.resolve({ path: ["view"] }),
    });
    await assert.rejects(view.text(), /Aborted/);
    assert.equal(timers[0].milliseconds, 35000);
  } finally {
    globalThis.fetch = originalFetch;
    AbortSignal.timeout = originalTimeout;
  }
});

test("NDJSON parser handles split UTF-8 and rejects truncated streams", async () => {
  const bytes = new TextEncoder().encode(JSON.stringify(event(0, "message_delta", { message: "选择" })) + "\n");
  const stream = new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  } });
  const events = [];
  await readRunEvents(new Response(stream), (event) => events.push(event));
  assert.equal(events[0].message, "选择");
  await assert.rejects(readRunEvents(new Response("{\"type\":"), () => {}), /ended during an event/);
});

test("large final answers survive fragmented NDJSON and render after streamed text", async () => {
  const text = "宇宙 is large. ".repeat(12000);
  const bytes = new TextEncoder().encode([
    event(0, "message_delta", { message: text.slice(0, 6000) }),
    event(1, "outcome", { outcome: { status: "completed", text, elements: [element] } }),
  ].map((item) => JSON.stringify(item) + "\n").join(""));
  const stream = new ReadableStream({ start(controller) {
    for (let offset = 0; offset < bytes.length; offset += 4096)
      controller.enqueue(bytes.slice(offset, offset + 4096));
    controller.close();
  } });
  let state = emptyDisplay();
  await readRunEvents(new Response(stream), (event) => { state = applyRunEvent(state, event); });
  assert.equal(state.text, text);
  assert.deepEqual(state.blocks.map((block) => block.kind), ["text", "element"]);
  assert.equal(state.blocks[0].text, text);
});

test("unknown response types, including prototype names, render the unsupported state", () => {
  const require = createRequire(import.meta.url);
  const ts = require("typescript");
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const source = readFileSync(new URL("../layers/input/web/app/runtime-elements.tsx", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS,
  } });
  const exported = {};
  new Function("require", "exports", outputText)(require, exported);
  for (const type of ["unknown", "constructor", "toString", "__proto__"]) {
    const markup = renderToStaticMarkup(React.createElement(exported.RuntimeElement, {
      element: { ...element, type }, disabled: false, onChoose() {},
    }));
    assert.match(markup, /Unsupported response element/);
  }
});

test("Stop after a pre-acknowledgement disconnect reconnects the identical request and cancels", async () => {
  const require = createRequire(import.meta.url);
  const ts = require("typescript");
  const source = readFileSync(new URL("../layers/input/web/app/use-runtime-chat.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const exported = {};
  const hooks = {
    useRef: (value) => ({ current: value }),
    useState: (value) => [value, () => {}],
    useEffect: () => {},
  };
  new Function("require", "exports", outputText)((name) => {
    if (name === "react") return hooks;
    if (name === "./runtime-client") return runtimeClient;
    return require(name);
  }, exported);

  const originalFetch = globalThis.fetch;
  const requests = [];
  const displays = [];
  let controller;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, payload: JSON.parse(options.body) });
    if (requests.length === 1) throw new Error("Connection lost before acknowledgement");
    if (url.endsWith("/run")) return new Response(new ReadableStream({ start(streamController) {
      controller = streamController;
      controller.enqueue(new TextEncoder().encode(JSON.stringify({ ...event(0, "progress"),
        request_id: requests[0].payload.request_id,
      }) + "\n"));
    } }));
    if (url.endsWith("/cancel")) {
      const request = requests[0].payload;
      controller.enqueue(new TextEncoder().encode(JSON.stringify({ ...event(1, "outcome"),
        request_id: request.request_id, outcome: { status: "cancelled", text: "Response cancelled.", elements: [] },
      }) + "\n"));
      controller.close();
      return Response.json({ run_id: "run-1", status: "running" });
    }
    throw new Error("Unexpected request");
  };
  try {
    const chat = exported.useRuntimeChat((_chatId, _requestId, display) => displays.push(display));
    assert.equal(chat.submit("chat", "Hello"), true);
    await new Promise((resolve) => setImmediate(resolve));
    await chat.cancel("chat");
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(requests.map((request) => request.url), [
      "/api/backend/runtime/run", "/api/backend/runtime/run", "/api/backend/runtime/cancel",
    ]);
    assert.deepEqual(requests[1].payload, requests[0].payload);
    const { text: _text, ...control } = requests[0].payload;
    assert.deepEqual(requests[2].payload, control);
    assert.equal(displays.at(-1)?.outcome?.status, "cancelled");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
