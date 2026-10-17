# Loke

A desktop neuroscience learning-partner scaffold, organized by **horizontal layers**.

```text
layers/
  input/                 # A: Next.js/React and Electron
    web/
    desktop/
  intelligence/          # B: FastAPI, coordinator, policy and model adapters
    loke_intelligence/
  memory/                # C: database, retrieval and durable records
    loke_memory/
shared/
  contracts/             # Pydantic, generated JSON Schema/TypeScript and ports
  fixtures/              # Shared fixture extension point
scripts/                 # Launcher and contract export
tests/                  # Cross-layer behavior checks
docs/                   # Ownership and setup
third_party/openpoke/    # Pinned source attribution and retained MIT license
```

## Start

Needs Python 3.11+, Node 22+ and uv. Docker is optional for PostgreSQL. Default demo mode runs with SQLite and no API keys.

```sh
cp .env.example .env
uv sync
npm install
npm run contracts:generate
npm run desktop
```

`npm run dev` runs the same app in a browser at http://127.0.0.1:3000. Backend health is at http://127.0.0.1:8000/healthz and contracts at /openapi.json. The launcher stops child services on Ctrl+C.

The scaffold uses a local session token passed by the Next.js server proxy, not by renderer code. Set your own SESSION_TOKEN in .env for local work. Do not expose this demo as a public multi-user service.

## What works

- Consent and goal setup, stable subject-agent identity and a deterministic study plan.
- MCQ/short-answer evidence, missed-item prerequisite selection and review scheduling.
- Text and Markdown report/source persistence; conceptual teaching resources and SVG sequence.
- Durable in-app review notifications with a visibly accelerated demo clock.
- Learning-history deletion, expiry and cross-layer typed contracts.
- Optional OpenRouter explanation and direct OpenAI transcription adapters.
- Chat agent runtime with bounded tool execution, streamed progress, Stop/Retry/Reset controls,
  and one model-authored multiple-choice response tool.

Demo mode uses reviewed cards and code rules. It does not simulate a successful audio transcription. Live APIs need explicit keys and billing; no key is needed to verify the core loop. Set MODEL_MODE=live for OpenRouter and OPENAI_API_KEY for audio. Review the layer README extension points before treating the scaffold as complete.

## Chat runtime

Chat now calls an independent agent runtime; it does not invoke learning policy or write
the learner database. In demo mode, ask for **options** to exercise the example tool,
then select an option to send an ordinary follow-up. The demo adapter supplies fixture
responses; `MODEL_MODE=live` uses server-side OpenRouter tool calling with the existing
`OPENROUTER_API_KEY`, `TEXT_MODEL` and `OPENROUTER_PROVIDER` configuration. Live chat
omits the completion-token cap and uses the provider/model default. Reasoning models
can additionally use `OPENROUTER_REASONING_EFFORT` (for example, `low`). Chat has no
total-duration deadline or application-imposed input, context or answer character limits.
Successful provider streams and frontend events have no cumulative size cutoff. Model-native
context and output capacity still apply; provider truncation is reported separately.

Provider failures return controlled, actionable messages. Server logs emit
`runtime_request_failed` with the run ID, error category, HTTP status and numeric provider
code when available, bounded provider request ID, model/provider settings, timing, call
counts and stack locations. Structured handlers can read the same `runtime_diagnostic`
record field. Completed provider responses emit `runtime_model_response` with safe stream
diagnostics and numeric prompt, completion and (when supplied) reasoning-token usage.
Logs omit raw exception messages, response bodies, headers, prompts and stack locals; use
the provider request ID to investigate further with the provider.

The engine in `agent_runtime.py` injects a model, tool registry and session store.
`runtime_tools.py` registers the single `generate_multiple_choice_response` handler
with strict input/output schemas, permission and execution limits. The UI maps the
`multiple_choice` element type to its renderer. Python runtime contracts live in
`shared/contracts/loke_contracts/runtime.py`; the normal exporter generates frontend types.

The authenticated proxy exposes POST `runtime/run` (`session_id`, `session_epoch`,
`request_id`, `text`), `runtime/cancel` (same identity fields without text), and
`runtime/reset` (`session_id`, `session_epoch`). Run responses are newline-delimited
`RunEvent` JSON: progress, `block_start`, `text_delta`, `block_end`, `tool_result`, then
one terminal `RunOutcome` with status, reason and usage. Each text segment and UI-producing
tool has a stable block ID. A model step streams its text and closes that block before
the runtime reserves the step's tool positions. All UI tool positions in a batch are
reserved before execution; results fill those positions instead of appending on arrival.
Tools without a public-element renderer do not reserve display blocks.

The UI renders a completed prefix plus its first streaming text block. A pending tool
or unfinished text blocks later content, even if that content is ready. Text is finalized
per block, so an explanation, card, caption, second card and closing text keep their order.
Tools still execute sequentially; the display queue also handles out-of-order completions.
The model must write prerequisite context before requesting the dependent tool. There is
no choice-specific placement setting or end-of-turn card buffer.

The outcome's ordered `blocks` snapshot is authoritative for reconnect and final replay;
flat `text` and `elements` remain convenience fields, not a way to reconstruct placement.
Failure and cancellation settle unfinished blocks and preserve partial text. Reset clears
old output, and late callbacks cannot modify completed steps. This replaces the previous
event protocol; restart the backend and reload the frontend together when updating.

Disconnect detaches the stream while the run continues until completion or cancellation. Retry
reuses the exact request and replays/attaches to that run. Stop explicitly cancels it;
unmount also attempts cancellation. Reset rotates the session epoch, cancels old runs
and clears conversation; stale outputs are ignored. These sessions are process-local:
backend/browser restarts lose continuity. The store keeps up to 100 session identities,
32 completed outcomes and 64 conversation groups per session, with at most eight active
or queued runs per session. Deduplication applies within the retained outcome window.

Default limits are four model calls, four tool calls and eight total calls. The final model
call reserves capacity to respond without more tools. Tool results are bounded to 6,000
characters, and each tool has a three-second timeout. Two tool errors trigger finalization.
Tool and call limits are injected via
`RunLimits`; stop reasons are explicit, and diagnostics record IDs, timing/status and usage.
The provider connection, write and pool timeouts are 20 seconds; the read inactivity timeout
is 120 seconds and resets when network data arrives, including reasoning or heartbeat data.
The proxy has no total-duration timer for `runtime/run`; other routes retain their 35-second
timeout. Failure and cancellation messages use the outcome's `notice` field, rendered as
status outside the answer. Partial answer text is preserved without adding notices to model
history.

Verify with `npm run check`, `node --test tests/test_runtime_client.mjs`, and a browser
pass covering options → card → selection → follow-up, Stop, Reset and reconnect/Retry.

## PostgreSQL

```sh
docker compose up -d
```

Set DATABASE_URL to the PostgreSQL value in .env.example and restart. Schema creation is bootstrap-only; C should add versioned migrations before expanding the data model. SQLite and PostgreSQL databases are separate; switching URLs does not migrate existing learner records.

## Verify

```sh
npm run check
npm run build
uv run ruff check .
```

Contract changes: edit Python models, regenerate schema/types, then typecheck. Do not edit generated files manually.

## Teammates and plan

- A: `layers/input/README.md`
- B: `layers/intelligence/README.md`
- C: `layers/memory/README.md`
- [Horizontal ownership](docs/HORIZONTAL_OWNERSHIP.md)
- [Weekend plan](WEEKEND_MVP_PLAN.md)
- [Team brief](TEAM_BRIEF.md)
- [OpenPoke reuse manifest](third_party/openpoke/REUSE.md)

See the ownership document for unfinished interfaces and acceptance work. Phone/SMS, broad media generation and automatic topic splitting remain deferred.
