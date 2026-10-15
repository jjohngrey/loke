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
  assert.equal(state.elements.length, 1);
  assert.equal(state.sequence, 3);
  assert.equal(applyRunEvent(state, { ...event(4, "element", { element }), run_id: "another" }), state);
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
