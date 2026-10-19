# Passage side chats

Select a passage in a saved Loke reply, type into `Ask about this…`, and press Enter.
The side chat opens immediately and streams its reply separately from the main chat.
Close it and click the source highlight to reopen it. The Side chats menu provides
keyboard access to every thread, including overlapping selections.

- Escape or an outside click dismisses an unsent selection.
- Control+L opens a nonempty selection draft without sending, or closes the panel.
- Enter sends a panel question; Shift+Enter inserts a newline.
- Show in chat returns to the source. On narrow screens it closes the panel.
- Closing keeps a request running. Stop cancels it; Retry replaces the failed turn.

Threads and drafts live only in the current page session, grouped by main chat.
Changing main chats retains them. Reloading or resetting learner history clears
them. Source removal, content changes or incompatible rendered offsets invalidate
anchors. Side questions and replies never enter the main transcript or assessment.

## Selection and rendering

`selection-index.ts` defines the versioned `loke-rendered-v1` UTF-16 stream.
It uses block newlines and table tabs, preserves literal Prism line breaks and
code whitespace, and excludes controls and hidden KaTeX MathML. One-character
selections are allowed so a single variable can be discussed. The minimum is one
non-whitespace UTF-16 code unit; selections above 20,000 units are ignored.

Highlights use per-text-leaf CSS Custom Highlights without changing the DOM.
This preserves syntax colors and equation layout and lets the browser clip and
reflow paint with scrollable code/math. A clipped rectangle fallback is available
when Custom Highlights are unavailable. Active overlapping threads take priority;
all threads remain reachable from the menu.

Math uses the existing renderer's `$…$` and `$$…$$` delimiters. Visible glyph text
is not lossless LaTeX, especially for fractions and matrices. The original Markdown
is sent separately; rendered offsets are never used to slice it.

## Intelligence boundary

The authenticated proxy forwards `POST /api/side-threads/reply` to Intelligence.
Its Python contract generates the public TypeScript. Each NDJSON event carries
thread/request identity. Input keeps the thread history; the server holds only
bounded active requests, with a 28-second deadline, no tools, and no memory writes.
The endpoint verifies storage consent and learner generation before answering.
The live adapter inherits the application's server model/provider configuration.
Demo mode streams an explicitly simulated source-aware reply.

Context contains the immutable quote/source, main history through that source,
completed side history and the latest question once. The complete source Markdown
is retained within the 100,000-character request limit. Main and side histories
use 12,000/16,000-character budgets; truncation is explicit in model context.

## Verification

```sh
npm ci
uv sync --group dev
npx playwright install chromium
npm run dev --workspace @loke/input-web -- --port 3105
# In a second terminal; all answers are mocked, no backend or provider is called:
npm run test:selection
npm run test:side-threads
.venv/bin/python -m pytest tests/test_side_threads.py -q
npm run typecheck
.venv/bin/ruff check layers/intelligence shared/contracts tests scripts/export_contracts.py
```

`LOKE_WEB_TEST_URL` overrides the browser-test URL. `LOKE_CHROMIUM_PATH` can select
an installed browser. `LOKE_SELECTION_SCREENSHOT` optionally saves a screenshot.
The browser fixture uses the actual workspace and Markdown renderer with mocked
network responses. It covers code/math capture/restoration and DOM stability,
physical code selection, repeated phrases, clipping, resizing, copying, keyboard,
mobile focus return and main reading position. Store/adapter tests cover separate
histories, final reconciliation, failure/retry, Stop and stale callbacks.

These checks establish mocked behavior, not live provider answer quality. Database
integration, real touch selection handles, screen readers, and other browser engines
need separate verification. No persistence schema or migration is involved.
