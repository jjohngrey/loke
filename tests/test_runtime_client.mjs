import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import * as runtimeClient from "../layers/input/web/app/runtime-client.ts";
const { applyRunEvent, emptyDisplay, readRunEvents, visibleBlocks } = runtimeClient;

const element = {
  type: "multiple_choice", element_id: "element-1", question: "Choose?",
  choices: [{ id: "a", text: "A" }, { id: "b", text: "B" }, { id: "c", text: "C" }],
};
const event = (sequence, type, fields = {}) => ({
  run_id: "run-1", request_id: "request-1", session_epoch: 0, sequence, type, ...fields,
});

const textBlock = (block_id, text = "", state = "streaming") => ({
  kind: "text", block_id, text, state,
});
const toolBlock = (block_id, state = "pending", elements = []) => ({
  kind: "tool", block_id, call_id: block_id, state, elements,
});
const finishEvent = (sequence, blocks, status = "completed") => event(sequence, "outcome", {
  outcome: { status, blocks, text: blocks.filter((block) => block.kind === "text")
    .map((block) => block.text).join("\n"), elements: [] },
});
const visibleIds = (state) => visibleBlocks(state.blocks).map((block) => block.block_id);

test("text-tool-text-tool-text keeps intermediate placement through replay and final snapshots", () => {
  const blocks = [textBlock("a", "Explanation.", "complete"), toolBlock("b", "ready", [element]),
    textBlock("c", "Caption.", "complete"), toolBlock("d", "ready", [{ ...element, element_id: "two" }]),
    textBlock("e", "Closing.", "complete")];
  const events = [];
  for (const block of blocks) {
    events.push(event(events.length, "block_start", { block: block.kind === "text"
      ? textBlock(block.block_id) : toolBlock(block.block_id) }));
    if (block.kind === "text") events.push(event(events.length, "text_delta", {
      block_id: block.block_id, message: block.text,
    }));
    events.push(event(events.length, block.kind === "text" ? "block_end" : "tool_result", { block }));
  }
  let state = events.reduce(applyRunEvent, emptyDisplay());
  assert.deepEqual(state.blocks, blocks);
  assert.deepEqual(visibleIds(state), ["a", "b", "c", "d", "e"]);
  const snapshot = finishEvent(events.length, blocks);
  state = applyRunEvent(state, snapshot);
  assert.deepEqual(events.reduce(applyRunEvent, state), state);
  assert.deepEqual(applyRunEvent(emptyDisplay(), snapshot).blocks, blocks);
  assert.equal(applyRunEvent(state, snapshot), state);
  assert.equal(applyRunEvent(state, event(999, "progress")), state);
});

test("ready tools and later text stay hidden until preceding text finishes", () => {
  const events = [
    event(0, "block_start", { block: textBlock("a") }),
    event(1, "text_delta", { block_id: "a", message: "An explanation" }),
    event(2, "block_start", { block: toolBlock("b") }),
    event(3, "tool_result", { block: toolBlock("b", "ready", [element]) }),
    event(4, "block_start", { block: textBlock("c") }),
    event(5, "text_delta", { block_id: "c", message: "A caption" }),
  ];
  let state = events.reduce(applyRunEvent, emptyDisplay());
  assert.deepEqual(visibleIds(state), ["a"]);
  assert.equal(state.blocks[0].text, "An explanation");
  state = applyRunEvent(state, event(6, "block_end", {
    block: textBlock("a", "An explanation", "complete"),
  }));
  assert.deepEqual(visibleIds(state), ["a", "b", "c"]);
  assert.equal(state.blocks[0].state, "complete");
  assert.equal(state.blocks[2].state, "streaming");
});

test("out-of-order tool completions fill reserved positions without overtaking", () => {
  let state = [event(0, "block_start", { block: toolBlock("first") }),
    event(1, "block_start", { block: toolBlock("second") }),
    event(2, "tool_result", { block: toolBlock("second", "ready", [element]) })]
    .reduce(applyRunEvent, emptyDisplay());
  assert.deepEqual(visibleIds(state), []);
  state = applyRunEvent(state, event(3, "tool_result", {
    block: toolBlock("first", "ready", [{ ...element, element_id: "first-card" }]),
  }));
  assert.deepEqual(visibleIds(state), ["first", "second"]);
  assert.equal(state.blocks[0].elements[0].element_id, "first-card");
});

test("a clarification with no preceding text appears as soon as its tool is ready", () => {
  let state = applyRunEvent(emptyDisplay(), event(0, "block_start", { block: toolBlock("question") }));
  assert.deepEqual(visibleIds(state), []);
  state = applyRunEvent(state, event(1, "tool_result", {
    block: toolBlock("question", "ready", [element]),
  }));
  assert.deepEqual(visibleIds(state), ["question"]);
  assert.equal(state.outcome, undefined);
});

for (const status of ["failed", "cancelled"]) {
  test(`${status} outcomes settle pending blocks and preserve partial text`, () => {
    let state = [event(0, "block_start", { block: textBlock("partial") }),
      event(1, "text_delta", { block_id: "partial", message: "Partial answer." }),
      event(2, "block_start", { block: toolBlock("pending") })]
      .reduce(applyRunEvent, emptyDisplay());
    const blocks = [textBlock("partial", "Partial answer.", status), toolBlock("pending", status)];
    state = applyRunEvent(state, finishEvent(3, blocks, status));
    assert.deepEqual(visibleIds(state), ["partial", "pending"]);
    assert.equal(state.text, "Partial answer.");
    assert.ok(state.blocks.every((block) => !["streaming", "pending"].includes(block.state)));
  });
}

test("a failed tool settles its position and allows subsequent text to stream", () => {
  const failed = { ...toolBlock("bad", "failed"), notice: "Could not prepare the diagram." };
  const state = [event(0, "block_start", { block: toolBlock("bad") }),
    event(1, "tool_result", { block: failed }),
    event(2, "block_start", { block: textBlock("recovery") }),
    event(3, "text_delta", { block_id: "recovery", message: "Here is an explanation instead." })]
    .reduce(applyRunEvent, emptyDisplay());
  assert.deepEqual(visibleIds(state), ["bad", "recovery"]);
  assert.equal(state.blocks[0].notice, failed.notice);
});

test("event gaps and unknown blocks require reconnect rather than silently changing order", () => {
  assert.throws(() => applyRunEvent(emptyDisplay(), event(1, "progress")), /missing an event/);
  assert.throws(() => applyRunEvent(emptyDisplay(), event(0, "text_delta", {
    block_id: "missing", message: "Text",
  })), /unexpected text/);
  assert.throws(() => applyRunEvent(emptyDisplay(), event(0, "tool_result", {
    block: toolBlock("missing", "ready", []),
  })), /unknown block/);
  const state = applyRunEvent(emptyDisplay(), event(0, "progress"));
  assert.equal(applyRunEvent(state, { ...event(1, "progress"), run_id: "other" }), state);
});

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
  const bytes = new TextEncoder().encode(JSON.stringify(event(0, "text_delta", { block_id: "text", message: "选择" })) + "\n");
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
    event(0, "block_start", { block: textBlock("long") }),
    event(1, "text_delta", { block_id: "long", message: text.slice(0, 6000) }),
    finishEvent(2, [textBlock("long", text, "complete"), toolBlock("choices", "ready", [element])]),
  ].map((item) => JSON.stringify(item) + "\n").join(""));
  const stream = new ReadableStream({ start(controller) {
    for (let offset = 0; offset < bytes.length; offset += 4096)
      controller.enqueue(bytes.slice(offset, offset + 4096));
    controller.close();
  } });
  let state = emptyDisplay();
  await readRunEvents(new Response(stream), (event) => { state = applyRunEvent(state, event); });
  assert.equal(state.text, text);
  assert.deepEqual(state.blocks.map((block) => block.kind), ["text", "tool"]);
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
        request_id: request.request_id, outcome: { status: "cancelled", text: "", notice: "Response cancelled.", elements: [], blocks: [] },
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
