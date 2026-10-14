# Current contract fixtures (v1)

B's first deliverable: a development-only baseline for A's UI and C's storage work.
These JSON files describe today's implemented contracts, not the proposed lifecycle extension.
No fixture route is added to the application. Never send fixture learner IDs/history to a real user session.

## For A: views and transport

Use the generated, typechecked `v1/views.ts` module in a local fixture adapter. JSON copies
are available for Python/storage consumers. For example, from `layers/input/web/`:

```ts
import { views } from "../../../shared/fixtures/v1/views";
const fixture = views["wrong-answer"];
```

| View | UI state / meaning |
| --- | --- |
| empty | No saved consent, goal, agent or personal records |
| saved-goal | Saved goal, reusable subject identity, offered quiz and initial plan |
| wrong-answer | Incorrect action-potential item; resting-potential diagnostic cites the actual event |
| ungraded-answer | Unclear answer is recorded, with no correctness projection or new review |
| assisted-correct | Correct retry after explanation; conservative state and earlier deadline retained |
| unassisted-correct | Correct first item; narrow item evidence and +72h review |
| sources | Uploaded text is reported activity plus source chunks, not correctness evidence |
| due-reminder | +24h visibly simulated clock; one notification and a review-first plan |
| reset | Post-delete empty view; revisions reset to zero, no generation field yet |

The cases are separate scenarios, not one ordered stream. Only wrong-answer → due-reminder → reset
belongs to the same scenario. Do not feed every file sequentially into a monotonic revision reducer.
Fixture observations use 2026-10-17 01:00 UTC (09:00 Asia/Shanghai). IDs are deterministic and
cross-referenced; timestamps are samples, not timestamps to reuse for real evidence.
Sources and transcription are synthetic examples; no successful paid provider call is claimed.

`v1/requests.json` supplies valid payloads. `v1/errors.json` supplies method/path/status/body examples.
The renderer uses `/api/backend/<suffix>`; A's proxy forwards to `/api/<suffix>` with server-only
`x-loke-session`. Learner identity is selected by the backend, never by these request payloads.

| HTTP method/path | Payload/example | Response |
| --- | --- | --- |
| GET /api/view | None | LearningView |
| POST /api/goal | goal | LearningView |
| POST /api/input | text, voice or attachment | LearningView |
| POST /api/quiz/answer | wrong_answer, ungraded_answer, prerequisite_answer, assisted_answer, unassisted_answer | LearningView |
| POST /api/reminders | reminders | LearningView |
| POST /api/demo/clock | clock (only when enabled) | LearningView |
| DELETE /api/learner | None | Empty LearningView |
| POST /api/audio/transcribe | Multipart `file`, `audio-consent: true`; saved goal required | TranscriptionResult, saved=false |

Audio success only fills an editable draft; explicit Send uses the voice input payload. The
transcription JSON is an adapter fixture, not an available offline transcription service.
`context.json` and `proposal.json` illustrate the current model boundary, without citation fields.

Errors use string `detail` for 400/403/409/502, but 422 uses FastAPI's validation-detail array.
For the 409 example, first save the goal and submit wrong_answer; reuse its ID with answer B.
For 502, use a mocked provider failure after saving a goal in live mode. Preserve drafts on errors.
Only goal/input/answer expose request IDs. Retry the exact ID and payload after uncertain delivery;
a confirmed conflict requires reload and a newly confirmed operation. Settings/clock are not yet retry-safe.

## For C: implemented MemoryPort semantics

`MemoryPort` now includes `learner_ids()`. The coordinator accepts this port; only app.py imports Store.
`tests/fakes.py` provides a typed, database-free reference adapter for baseline behavior. It is
single-threaded, volatile and for tests only; it does not prove SQL durability or concurrency safety.

Current snapshot fields:

- Profile: goal, storage_consent, reminders_enabled, study_minutes, agent_id, response,
  active_card_id, assisted_concepts, state_revision, plan_revision, demo_clock_hours, expires_at.
- Collections: states (dict keyed by concept ID), events, sources, plan, notifications, review_jobs.
- Event/state/source/plan/notification values follow the public models. Internal notifications also
  carry kind=notification. Review jobs carry id/kind/concept_id/reason_event_id/due_at/status.
  Status is pending or notified; the current implementation has no lease.

`snapshot` returns an isolated readable snapshot. Missing learners return an empty profile without
persisting consented history. `learner_ids` enumerates persisted learners. Source/event reads stay
learner-scoped; retrieval returns up to two positively matching chunks, with an empty no-match result.

`mutate(learner_id, request_id, fingerprint, expected_revision, transform)` is the current atomic boundary:

1. Dedupe is scoped by learner and request ID (not yet by operation/generation).
2. Same fingerprint returns the original stored outcome, even if newer state exists. It does not
   rerun transform or increment revisions. Different fingerprint raises a ValueError-compatible conflict.
3. After dedupe, a supplied expected revision must equal current state_revision; otherwise nothing commits.
4. Transform runs against the current snapshot. Its exception rolls back all changes and publishes no outcome.
5. Success persists profile, new events, projections, sources, plan, jobs and outcome together; state_revision
   increases once, even for a no-op transform in today's implementation. Coordinator controls plan_revision.

The current Store uses concrete ConflictError, translated to HTTP 409 by app.py. The fake raises its own
ValueError subclass so policy tests do not import the SQL implementation. A shared conflict type,
typed snapshots/commands and meaningful no-op revisions remain proposed work.

Delete removes learner-scoped records and dedupe outcomes, retaining the curated catalog. Expiry uses
wall time and the profile's seven-day deadline. Event replay, graph versions, generation safety,
bounded caches, multi-worker claims and notification actions are not provided by this fixture pack.

## Validate and regenerate

```sh
.venv/bin/python -m pytest tests/test_contract_fixtures.py
.venv/bin/python -m tests.fixture_scenarios
npm run contracts:generate
npm run typecheck
./node_modules/.bin/tsc --noEmit --strict --skipLibCheck --moduleResolution bundler --module esnext shared/fixtures/v1/views.ts
```

The explicit scenario command rewrites fixture JSON only. Tests compare every published view with
the current coordinator against both FakeMemory and SQLite Store, validate Pydantic payloads and
cross-references, and exercise rollback/dedupe/isolation at both memory implementations.
OpenAPI at `/openapi.json` declares LearningView, TranscriptionResult and string-detail errors;
422 retains HTTPValidationError. No new learner action endpoint is introduced.

## Next contract slice needs A/C review

The [shared extension proposal](../../layers/intelligence/README.md#shared-extension-proposal-not-implemented-yet)
remains a proposal: generation/version envelopes, activity/attempt lifecycle, assistance reset and
notification actions must be agreed and persisted together. They are not v1 fixture fields.
Before changing required fields, A confirms action/render/reset semantics and C confirms migration,
transaction and retention semantics. Keep future fixture versions separate until their models exist.
