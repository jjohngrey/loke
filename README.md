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

Demo mode uses reviewed cards and code rules. It does not simulate a successful audio transcription. Live APIs need explicit keys and billing; no key is needed to verify the core loop. Set MODEL_MODE=live for OpenRouter and OPENAI_API_KEY for audio. Review the layer README extension points before treating the scaffold as complete.

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
