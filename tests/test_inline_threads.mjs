import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { readFileSync } from "node:fs";
import { chromium } from "playwright";
import ts from "typescript";

const markdown = readFileSync(new URL("./fixtures/inline-threads.md", import.meta.url), "utf8");
const view = JSON.parse(readFileSync(new URL("../shared/fixtures/v1/views/saved-goal.json", import.meta.url)));
const indexCode = ts.transpileModule(readFileSync(new URL("../layers/input/web/app/selection-index.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
let browser;
before(async () => { browser = await chromium.launch({ headless: true, executablePath: process.env.LOKE_CHROMIUM_PATH }); });
after(async () => { await browser?.close(); });

export async function fixture(options = {}) {
  const { sideReply, ...browserOptions } = options;
  let sourceMarkdown = markdown;
  const context = await browser.newContext({ viewport: { width: 1400, height: 1000 }, ...browserOptions });
  const page = await context.newPage();
  const requests = [];
  await page.route("**/api/backend/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/backend/", "");
    requests.push({ path, body: route.request().postDataJSON() });
    if (path === "side-threads/reply") {
      const body = route.request().postDataJSON();
      if (sideReply) return sideReply(route, body);
      const text = `Mock side answer about ${body.anchor.selected_text}: ${body.question}`;
      const event = (type, text) => JSON.stringify({ thread_id: body.thread_id, request_id: body.request_id, type, text }) + "\n";
      await route.fulfill({ contentType: "application/x-ndjson", body: event("delta", "Mock side ") + event("completed", text) });
      return;
    }
    const responses = {
      view: { ...view, active_quiz: null },
      capabilities: { audio_available: false, model_mode: "demo" },
      workspace: { generation_id: view.generation_id, state_revision: view.state_revision, folders: [], chats: [
        { id: "rich-chat", title: "Rich selection fixture" }, { id: "other-chat", title: "Other chat" },
      ] },
      "chats/history": { generation_id: view.generation_id, has_more: false, messages: [
        { id: "user-1", role: "user", text: "Explain these examples", sequence: 1 },
        { id: "source-1", role: "assistant", text: sourceMarkdown, sequence: 2 },
      ] },
    };
    await route.fulfill({ json: responses[path] || {} });
  });
  await page.goto(process.env.LOKE_WEB_TEST_URL || "http://127.0.0.1:3105");
  await page.getByRole("button", { name: "Rich selection fixture", exact: true }).click();
  await page.locator(".message.loke .katex-html").first().waitFor();
  await page.addScriptTag({ content: `{ const exports = {}; ${indexCode}; window.selectionTest = exports; }` });
  return { context, page, requests, updateSource: (text) => { sourceMarkdown = text; } };
}

const rootSelector = ".message.loke .message-content";

test("canonical stream preserves Prism lines, tabs and blank lines; excludes code chrome and MathML", async () => {
  const { page, context } = await fixture();
  try {
    const result = await page.evaluate((selector) => {
      const root = document.querySelector(selector);
      const { buildTextIndex } = window.selectionTest;
      const index = buildTextIndex(root);
      return { text: index.text, code: root.querySelector("pre").textContent,
        math: [...root.querySelectorAll(".katex-html")].map((el) => buildTextIndex(el).text),
        mathml: root.querySelector(".katex-mathml").textContent };
    }, rootSelector);
    assert.match(result.text, /alpha = 1\n\tbeta = alpha \+ 2\n\n    gamma/);
    assert.match(result.code, /literal \$x\^2\$/);
    assert.doesNotMatch(result.text, /python|Copy|\\begin|\\frac/);
    assert.match(result.text, /First list item\nSecond list item/);
    assert.match(result.text, /Name\tValue\nSodium\t42/);
    assert.equal(result.text.split(result.math[0]).length - 1, 1);
    assert.equal(result.text.includes(result.mathml), false);
  } finally { await context.close(); }
});

test("repeated text, partial code tokens and visible math round trip without changing layout or offsets", async () => {
  const { page, context } = await fixture();
  try {
    const result = await page.evaluate((selector) => {
      const root = document.querySelector(selector);
      const { buildTextIndex, restoreRanges, captureRange } = window.selectionTest;
      const index = buildTextIndex(root);
      const phrases = ["repeated phrase", "beta = alpha + 2\n\n    gamma", "bc−ad", "🧠"];
      return phrases.map((phrase) => {
        const start = phrase === "repeated phrase" ? index.text.lastIndexOf(phrase) : index.text.indexOf(phrase);
        if (start < 0) return { phrase, missing: true };
        const ranges = restoreRanges(index, start, start + phrase.length);
        const range = document.createRange();
        range.setStart(ranges[0].startContainer, ranges[0].startOffset);
        range.setEnd(ranges.at(-1).endContainer, ranges.at(-1).endOffset);
        const before = root.querySelector(".katex-display").getBoundingClientRect().toJSON();
        CSS.highlights.set("test-selection", new Highlight(...ranges));
        const captured = captureRange(root, range);
        const after = root.querySelector(".katex-display").getBoundingClientRect().toJSON();
        const unchanged = index.text === buildTextIndex(root).text;
        return { phrase, captured, start, before, after, unchanged, leaves: ranges.length };
      });
    }, rootSelector);
    for (const item of result) {
      assert.equal(item.missing, undefined, item.phrase);
      assert.equal(item.captured.selectedText, item.phrase);
      assert.equal(item.captured.startOffset, item.start);
      assert.equal(item.unchanged, true);
      assert.deepEqual(item.before, item.after);
    }
  } finally { await context.close(); }
});

test("capture rejects excluded controls, cross-root and whitespace selections; accepts one math variable", async () => {
  const { page, context } = await fixture();
  try {
    const result = await page.evaluate((selector) => {
      const root = document.querySelector(selector);
      const { buildTextIndex, captureRange, restoreRanges } = window.selectionTest;
      const button = root.querySelector(".chat-code-header button");
      const excluded = document.createRange(); excluded.selectNodeContents(button);
      const cross = document.createRange(); cross.setStart(document.querySelector(".message.user p").firstChild, 0); cross.setEnd(root.querySelector("p").firstChild, 3);
      const index = buildTextIndex(root);
      const start = index.text.indexOf("a2");
      const single = restoreRanges(index, start, start + 1)[0];
      return { excluded: captureRange(root, excluded), cross: captureRange(root, cross), single: captureRange(root, single) };
    }, rootSelector);
    assert.equal(result.excluded, null);
    assert.equal(result.cross, null);
    assert.equal(result.single.selectedText, "a");
  } finally { await context.close(); }
});

async function selectQuote(page, phrase, occurrence = 0) {
  await page.evaluate(({ phrase, occurrence }) => {
    const root = document.querySelector("[data-message-content]");
    const { buildTextIndex, restoreRanges } = window.selectionTest;
    const index = buildTextIndex(root);
    let start = -1;
    for (let i = 0; i <= occurrence; i++) start = index.text.indexOf(phrase, start + 1);
    if (start < 0) throw new Error(`Missing quote: ${phrase}`);
    const ranges = restoreRanges(index, start, start + phrase.length);
    ranges[0].startContainer.parentElement.scrollIntoView({ block: "center", inline: "nearest" });
    const range = document.createRange(); range.setStart(ranges[0].startContainer, ranges[0].startOffset);
    range.setEnd(ranges.at(-1).endContainer, ranges.at(-1).endOffset);
    window.getSelection().removeAllRanges(); window.getSelection().addRange(range);
    root.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
  }, { phrase, occurrence });
  await page.getByRole("textbox", { name: "Ask about this passage" }).waitFor();
}

async function ask(page, question) {
  await page.getByRole("textbox", { name: "Ask about this passage" }).fill(question);
  await page.getByRole("textbox", { name: "Ask about this passage" }).press("Enter");
  await page.getByRole("complementary", { name: "Side chat" }).waitFor();
}

test("popover submits into an isolated panel, reopens the same occurrence, and preserves main draft", async () => {
  const { page, context } = await fixture();
  try {
    await page.locator("#message-input").fill("Keep main draft");
    await selectQuote(page, "repeated phrase", 1);
    await ask(page, "Why repeated?");
    await page.getByRole("button", { name: "Send question" }).waitFor();
    const sourceText = await page.locator("[data-message-content]").textContent();
    assert.equal(await page.locator("#message-input").inputValue(), "Keep main draft");
    await page.getByRole("textbox", { name: "Side chat question" }).fill("Keep thread A draft");
    await page.getByRole("button", { name: "Close side chat" }).click();
    await selectQuote(page, "beta = alpha + 2\n\n    gamma");
    await ask(page, "What does the code do?");
    await page.getByRole("button", { name: "Send question" }).waitFor();
    await page.getByRole("button", { name: "Close side chat" }).click();
    await page.getByText("Side chats (2)", { exact: true }).click();
    await page.getByRole("button", { name: /^Open side chat 1:/ }).click();
    assert.equal(await page.getByRole("textbox", { name: "Side chat question" }).inputValue(), "Keep thread A draft");
    assert.equal(await page.locator("[data-message-content]").textContent(), sourceText);
    const highlighted = await page.evaluate(() => [...CSS.highlights.get("loke-side-active")].map((range) => range.toString()).join(""));
    assert.equal(highlighted, "repeated phrase");
    const occurrence = await page.evaluate(() => {
      const root = document.querySelector("[data-message-content]");
      const index = window.selectionTest.buildTextIndex(root);
      const range = [...CSS.highlights.get("loke-side-active")][0];
      return { actual: window.selectionTest.endpointOffset(index, range.startContainer, range.startOffset, "start"), expected: index.text.lastIndexOf("repeated phrase") };
    });
    assert.equal(occurrence.actual, occurrence.expected);
    await page.getByRole("textbox", { name: "Side chat question" }).press("Control+l");
    assert.equal(await page.getByRole("complementary", { name: "Side chat" }).count(), 0);
  } finally { await context.close(); }
});

test("math fragment highlight survives resize and horizontal code scroll without DOM changes", async () => {
  const { page, context } = await fixture({ permissions: ["clipboard-read", "clipboard-write"] });
  try {
    const before = await page.locator(".katex-display .katex-html").innerHTML();
    await selectQuote(page, "bc−ad");
    await ask(page, "Explain this numerator");
    await page.getByRole("button", { name: "Send question" }).waitFor();
    const painted = await page.evaluate(() => [...CSS.highlights.get("loke-side-active")].map((range) => ({ text: range.toString(), parent: range.startContainer.parentElement.className })));
    assert.equal(painted.map((part) => part.text).join(""), "bc−ad");
    assert.ok(painted.every((part) => !part.parent.includes("mathml")));
    assert.equal(await page.locator(".katex-display .katex-html").innerHTML(), before);
    if (process.env.LOKE_SELECTION_SCREENSHOT) await page.screenshot({ path: process.env.LOKE_SELECTION_SCREENSHOT });
    await page.getByRole("slider", { name: "Side chat width" }).fill("560");
    await page.getByRole("button", { name: "Close side chat" }).click();
    await selectQuote(page, "alpha + 2");
    await ask(page, "Code fragment");
    await page.locator("[data-message-content] pre").evaluate((el) => { el.scrollLeft = 160; });
    const geometry = await page.evaluate(() => {
      const root = document.querySelector("[data-message-content]");
      const pre = root.querySelector("pre"); const box = pre.getBoundingClientRect();
      const ranges = [...CSS.highlights.get("loke-side-active")];
      return { scroll: pre.scrollLeft, text: ranges.map((range) => range.toString()).join(""),
        clipped: ranges.flatMap((range) => window.selectionTest.visibleRects(range, root)).every((r) => r.left >= box.left && r.right <= box.right) };
    });
    assert.ok(geometry.scroll > 0); assert.equal(geometry.text, "alpha + 2"); assert.equal(geometry.clipped, true);
    await page.locator("[data-message-content] .chat-code-header button").click();
    const clipboard = await page.evaluate(() => navigator.clipboard.readText());
    assert.match(clipboard, /alpha = 1\n\tbeta/); assert.match(clipboard, /print\(alpha/);
  } finally { await context.close(); }
});

test("Escape, outside click, draft shortcut and narrow-screen source navigation", async () => {
  const { page, context, requests } = await fixture({ viewport: { width: 390, height: 844 } });
  try {
    await selectQuote(page, "a2");
    await page.getByRole("textbox", { name: "Ask about this passage" }).press("Escape");
    assert.equal(await page.getByRole("form", { name: "Ask about selected passage" }).count(), 0);
    await selectQuote(page, "a2");
    await page.getByRole("textbox", { name: "Ask about this passage" }).fill("Unsent math question");
    await page.getByRole("textbox", { name: "Ask about this passage" }).press("Control+l");
    await page.getByRole("dialog", { name: "Side chat" }).waitFor();
    assert.equal(await page.getByRole("textbox", { name: "Side chat question" }).inputValue(), "Unsent math question");
    assert.equal(requests.some((request) => request.path.includes("side")), false);
    await page.getByRole("button", { name: "Show in chat" }).click();
    assert.equal(await page.getByRole("dialog", { name: "Side chat" }).count(), 0);
    assert.equal(await page.locator(".conversation").evaluate((el) => el.inert), false);
    await page.waitForFunction(() => document.activeElement?.hasAttribute("data-message-content"));
  } finally { await context.close(); }
});


test("physical pointer drag captures a partial Prism identifier and source clicks reopen without a new request", async () => {
  const { page, context, requests } = await fixture();
  try {
    const positions = await page.evaluate(() => {
      const root = document.querySelector("[data-message-content]");
      const index = window.selectionTest.buildTextIndex(root);
      const start = index.text.indexOf("beta");
      const ranges = window.selectionTest.restoreRanges(index, start, start + 3);
      ranges[0].startContainer.parentElement.scrollIntoView({ block: "center" });
      const first = ranges[0].getBoundingClientRect();
      return { x1: first.left + .5, x2: first.right - .5, y: first.top + first.height / 2 };
    });
    await page.mouse.move(positions.x1, positions.y); await page.mouse.down();
    await page.mouse.move(positions.x2, positions.y, { steps: 12 }); await page.mouse.up();
    await page.getByRole("textbox", { name: "Ask about this passage" }).waitFor();
    const quote = await page.locator(".selection-popover blockquote").textContent();
    assert.ok(quote.length >= 2 && quote.length < 5, quote);
    await ask(page, "What is this identifier?");
    await page.getByRole("button", { name: "Send question" }).waitFor();
    await page.getByRole("button", { name: "Close side chat" }).click();
    const point = await page.evaluate(() => {
      const range = [...CSS.highlights.get("loke-side")][0];
      const rect = range.getBoundingClientRect(); return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });
    await page.mouse.click(point.x, point.y);
    await page.getByRole("complementary", { name: "Side chat" }).waitFor();
    assert.equal(requests.filter((r) => r.path === "side-threads/reply").length, 1);
  } finally { await context.close(); }
});

test("popover copy uses the source before editing and normal input copy afterward; dismissal sends nothing", async () => {
  const { page, context, requests } = await fixture();
  try {
    await selectQuote(page, "code_token");
    const untouched = await page.locator("#passage-question").evaluate((input) => {
      const data = new DataTransfer(); const event = new ClipboardEvent("copy", { bubbles: true, cancelable: true, clipboardData: data }); input.dispatchEvent(event);
      return { prevented: event.defaultPrevented, text: data.getData("text/plain") };
    });
    assert.deepEqual(untouched, { prevented: true, text: "code_token" });
    await page.locator("#passage-question").fill("Edited"); await page.locator("#passage-question").fill("");
    const edited = await page.locator("#passage-question").evaluate((input) => {
      const event = new ClipboardEvent("copy", { bubbles: true, cancelable: true, clipboardData: new DataTransfer() }); input.dispatchEvent(event); return event.defaultPrevented;
    });
    assert.equal(edited, false);
    await page.locator(".conversation-topline").click({ position: { x: 200, y: 20 } });
    assert.equal(await page.locator(".selection-popover").count(), 0);
    assert.equal(requests.filter((r) => r.path === "side-threads/reply").length, 0);
  } finally { await context.close(); }
});

test("workspace polling preserves the main reading position while using the side panel", async () => {
  const { page, context, requests } = await fixture();
  try {
    await selectQuote(page, "repeated phrase", 1); await ask(page, "Keep my place");
    await page.getByRole("button", { name: "Send question" }).waitFor();
    await page.locator(".conversation-body").evaluate((el) => { el.scrollTop = 30; });
    const top = await page.locator(".conversation-body").evaluate((el) => el.scrollTop);
    const count = requests.filter((r) => r.path === "workspace").length;
    await page.waitForFunction(() => true);
    await new Promise((resolve) => setTimeout(resolve, 5500));
    assert.ok(requests.filter((r) => r.path === "workspace").length > count);
    assert.equal(await page.locator(".conversation-body").evaluate((el) => el.scrollTop), top);
    await page.getByRole("button", { name: "Close side chat" }).click();
    await page.getByRole("button", { name: "Other chat", exact: true }).click();
    assert.equal(await page.locator(".side-thread-links").count(), 0);
    await page.getByRole("button", { name: "Rich selection fixture", exact: true }).click();
    await page.getByText("Side chats (1)", { exact: true }).waitFor();
  } finally { await context.close(); }
});


test("retry and Stop keep one question and reject a delayed response", async () => {
  let attempt = 0, release;
  const waiting = new Promise((resolve) => { release = resolve; });
  const { page, context, requests } = await fixture({ sideReply: async (route, body) => {
    attempt++;
    const event = (type, text) => JSON.stringify({ thread_id: body.thread_id, request_id: body.request_id, type, text }) + "\n";
    if (attempt === 1) return route.fulfill({ contentType: "application/x-ndjson", body: event("error", "Try again") });
    if (attempt === 2) { await waiting; await route.fulfill({ contentType: "application/x-ndjson", body: event("completed", "Stale answer") }).catch(() => {}); return; }
    return route.fulfill({ contentType: "application/x-ndjson", body: event("completed", "Recovered answer") });
  } });
  try {
    await selectQuote(page, "code_token"); await ask(page, "Explain this token");
    await page.getByRole("button", { name: "Retry reply" }).waitFor();
    await page.getByRole("button", { name: "Retry reply" }).click();
    await page.getByRole("button", { name: "Stop reply" }).click();
    await page.getByRole("button", { name: "Retry reply" }).click();
    await page.getByText("Recovered answer", { exact: true }).waitFor();
    release();
    assert.equal(await page.locator(".side-thread-message.user").count(), 1);
    assert.equal(await page.getByText("Stale answer", { exact: true }).count(), 0);
    const sent = requests.filter((r) => r.path === "side-threads/reply").map((r) => r.body);
    assert.ok(sent.every((body) => body.question === "Explain this token" && body.history.length === 0));
    assert.equal(new Set(sent.map((body) => body.thread_id)).size, 1);
  } finally { release(); await context.close(); }
});

test("closing a running thread keeps its response isolated while another thread is active", async () => {
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  const { page, context } = await fixture({ sideReply: async (route, body) => {
    if (body.question === "Question A") await waiting;
    const text = body.question === "Question A" ? "Answer A" : "Answer B";
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ thread_id: body.thread_id, request_id: body.request_id, type: "completed", text }) + "\n" });
  } });
  try {
    await selectQuote(page, "code_token"); await ask(page, "Question A");
    await page.getByRole("button", { name: "Stop reply" }).waitFor();
    await page.getByRole("button", { name: "Close side chat" }).click();
    await selectQuote(page, "a2"); await ask(page, "Question B");
    await page.getByText("Answer B", { exact: true }).waitFor();
    release();
    assert.equal(await page.getByText("Answer A", { exact: true }).count(), 0);
    await page.getByRole("button", { name: "Close side chat" }).click();
    await page.getByText("Side chats (2)", { exact: true }).click();
    await page.getByRole("button", { name: /^Open side chat 1:/ }).click();
    await page.getByText("Answer A", { exact: true }).waitFor();
    assert.equal(await page.getByText("Answer B", { exact: true }).count(), 0);
  } finally { release(); await context.close(); }
});

test("source changes invalidate the thread rather than relocating an identical quote", async () => {
  const { page, context, updateSource } = await fixture();
  try {
    await selectQuote(page, "repeated phrase", 1); await ask(page, "Anchor question");
    await page.getByRole("button", { name: "Send question" }).waitFor();
    updateSource("Changed source with repeated phrase elsewhere.");
    await page.waitForFunction(() => document.querySelector("[data-message-content]")?.textContent.includes("Changed source"));
    await page.waitForFunction(() => !document.querySelector(".side-thread-panel"));
    assert.equal(await page.locator(".side-thread-links").count(), 0);
    assert.equal(await page.evaluate(() => CSS.highlights.get("loke-side-active")?.size || 0), 0);
  } finally { await context.close(); }
});
