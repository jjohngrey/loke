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
`OPENROUTER_API_KEY`, `TEXT_MODEL` and `OPENROUTER_PROVIDER` configuration.

Provider failures return controlled, actionable messages. Server logs emit
`runtime_request_failed` with the run ID, error category, HTTP status and numeric provider
code when available, bounded provider request ID, model/provider settings, timing, call
counts and stack locations. Structured handlers can read the same `runtime_diagnostic`
record field. Logs omit raw exception messages, response bodies, headers, prompts and
stack locals; use the provider request ID to investigate further with the provider.

The engine in `agent_runtime.py` injects a model, tool registry and session store.
`runtime_tools.py` registers the single `generate_multiple_choice_response` handler
with strict input/output schemas, permission and execution limits. The UI maps the
`multiple_choice` element type to its renderer. Python runtime contracts live in
`shared/contracts/loke_contracts/runtime.py`; the normal exporter generates frontend types.

The authenticated proxy exposes POST `runtime/run` (`session_id`, `session_epoch`,
`request_id`, `text`), `runtime/cancel` (same identity fields without text), and
`runtime/reset` (`session_id`, `session_epoch`). Run responses are newline-delimited
`RunEvent` JSON: ordered progress, text deltas, validated elements, then one terminal
`RunOutcome` with status, reason and usage. Public text deltas append; the outcome text
is authoritative. Cards merge by run/element ID across progress and final replay.

Disconnect detaches the stream while the run continues within its deadline. Retry
reuses the exact request and replays/attaches to that run. Stop explicitly cancels it;
unmount also attempts cancellation. Reset rotates the session epoch, cancels old runs
and clears conversation; stale outputs are ignored. These sessions are process-local:
backend/browser restarts lose continuity. The store keeps up to 100 session identities,
32 completed outcomes and 64 conversation groups per session, with at most eight active
or queued runs per session. Deduplication applies within the retained outcome window.

Default limits are four model calls, four tool calls, eight total calls and a 28-second
deadline including queue time, below the proxy's 35-second timeout. The final model call
reserves capacity to respond without more tools. Provider context includes at most
24,000 serialized characters, text output 6,000, tool results 6,000, and each tool has
a three-second timeout. Two tool errors trigger finalization. Limits are injected via
`RunLimits`; stop reasons are explicit, and diagnostics record IDs, timing/status and usage.

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
