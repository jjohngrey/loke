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
  const context = await browser.newContext({ viewport: { width: 1400, height: 1000 }, ...options });
  const page = await context.newPage();
  const requests = [];
  await page.route("**/api/backend/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/backend/", "");
    requests.push({ path, body: route.request().postDataJSON() });
    const responses = {
      view: { ...view, active_quiz: null },
      capabilities: { audio_available: false, model_mode: "demo" },
      workspace: { generation_id: view.generation_id, state_revision: view.state_revision, folders: [], chats: [
        { id: "rich-chat", title: "Rich selection fixture" }, { id: "other-chat", title: "Other chat" },
      ] },
      "chats/history": { generation_id: view.generation_id, has_more: false, messages: [
        { id: "user-1", role: "user", text: "Explain these examples", sequence: 1 },
        { id: "source-1", role: "assistant", text: markdown, sequence: 2 },
      ] },
    };
    await route.fulfill({ json: responses[path] || {} });
  });
  await page.goto(process.env.LOKE_WEB_TEST_URL || "http://127.0.0.1:3105");
  await page.getByRole("button", { name: "Rich selection fixture", exact: true }).click();
  await page.locator(".message.loke .katex-html").first().waitFor();
  await page.addScriptTag({ content: `{ const exports = {}; ${indexCode}; window.selectionTest = exports; }` });
  return { context, page, requests };
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
        const start = index.text.indexOf(phrase);
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
