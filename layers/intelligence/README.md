# B: intelligence implementation handoff

## Your persona and outcome

Act as the learning-policy and integration owner. Build a deterministic, evidence-linked learning loop with bounded model assistance. Own concept interpretation, assessment, activity selection, explanation validation, audio normalization, reminder eligibility and the public Python contracts. Treat model output as a proposal, never as learner knowledge or permission to write storage.

This is the handoff to give your coding agent. Read [the input handoff](../input/README.md), [memory ownership](../memory/README.md), [horizontal ownership](../../docs/HORIZONTAL_OWNERSHIP.md) and [weekend specification](../../WEEKEND_MVP_PLAN.md). A builds the experience, B owns teaching policy and contract publication, C owns storage/migrations/retrieval and the reviewed catalog. Keep one FastAPI application with logical layers, one subject root agent and a local desktop demo.

Your delivery is the real loop: goal and consent create/reuse a subject agent, a short plan chooses a question, a wrong answer commits evidence/state/plan/review together, an unchecked prerequisite is offered automatically, restart preserves the outcome and a due review creates one durable opt-in notification. Claims remain narrow: a report is not assessment, an item answer is not validated mastery, and a due date is a scheduling heuristic rather than measured forgetting.

Standalone policy work now lives in `learning_policy.py`/`learning_models.py`, with semantic
interpretation in `semantics.py` and an optional `semantic_openrouter.py` adapter. See
[learning-policy design and offline scenarios](../../docs/LEARNING_POLICY.md). This core is not
yet wired to the HTTP coordinator; the audited application gaps below still describe that app.

Source-scoped graph discovery is now available independently of the catalog: see
[source-graph pipeline and examples](../../docs/SOURCE_GRAPH_DISCOVERY.md). It preserves exact
citations and labels inferred prerequisites, with an optional model adapter and offline demo.
PDF/text upload, graph persistence and the learner UI remain integration work.

## Files and authority

| Area | Responsibility |
| --- | --- |
| `loke_intelligence/app.py` | Composition root, HTTP wiring/auth, validation/errors and lifecycle. Only this intelligence module imports the memory implementation. |
| `coordinator.py` | Consent-aware use cases, bounded context, agent reuse, version checks and authoritative turn orchestration. |
| `policy.py` | Code grading, association, prerequisite traversal, plan selection, assistance and review rules. |
| `openrouter.py` | Typed, bounded provider proposal, allowed IDs/citations, timeout and fallback. Preserve reuse notices. |
| `audio.py` | Direct OpenAI transcription, format/size/duration checks, timeout and safe errors. No audio persistence. |
| `scheduler.py` | Worker lifecycle and policy eligibility orchestration. Persist/claim through a port; no SQL or LLM calls here. |
| `shared/contracts/loke_contracts/models.py`, `ports.py` | B owns Python boundary shape. A/C review affected interfaces. B regenerates JSON Schema/TypeScript and publishes examples. |
| Catalog, memory tables/store/retrieval | C owns. Propose changes with stable IDs; do not duplicate graph/answer keys or implement a private database. |
| Input proxy, UI, desktop | A owns. Publish exact HTTP method/path/payload/error examples so A can update its allowlist. |

Shared root files/tests need coordinated narrow edits. Any domain conflict exception belongs in the shared boundary if policy/coordinator need it; the current concrete `ConflictError` is handled in app.py. Do not introduce concrete store imports elsewhere. Shared contracts are the first deliverable, not work postponed until the backend is finished.

## Audited baseline and gaps

Current implementation supports demo-mode goal/input/answer, a stable stored subject agent ID, deterministic three-step planning, source chunks, atomic snapshot mutation, deduplicated goal/input/answer outcomes, bounded live proposal, audio transcription and single-worker durable reminders. It uses SQLite by default; PostgreSQL has configuration but must be verified independently. No provider credentials are required for the core loop.

The code does not yet implement several specification promises:

- `MemoryPort` uses mutable `dict[str, Any]` snapshots and callbacks. Scheduler enumeration (`learner_ids`) is now declared in the protocol. `ContextBundle` is typed but not a complete storage port.
- Graph is represented by catalog prerequisite lists, not typed versioned edges. `choose_plan` checks only direct prerequisites, hardcodes fallback concepts, and has no completed-activity tracking. Every `_replan` increments plan revision, whether or not the plan meaningfully changes.
- `active_card_id` means an offered question. There is no persisted attempt lifecycle, active-quiz suppression or notification action/snooze API. Reports and scheduler replans can replace the offered card.
- `assisted_concepts` persists indefinitely. After an explanation the concept stays assisted across future independent sessions. This is conservative but cannot support a meaningful later unassisted review.
- `match_concept` uses substring scoring and silently picks the first tied concept. Clarification and bounded token matching remain work.
- Live proposal failures raise 502; deterministic fallback is not implemented. Proposals have no machine-verifiable citations or uncertainty. One provider call currently occurs per live report, including before a duplicate is recognized at commit.
- Audio checks suffix and bytes but not decoded media type/duration. Transcription success returns unsaved text; no transcript enters memory before confirmation.
- Due selection happens before the dispatch transaction. Inside it, consent, reminders, latest evidence, clock and daily cap are not all rechecked. Scheduler iterates all learners but is intentionally single-worker, without leases.
- Evidence timestamps currently use the shifted demo clock. This conflicts with the specification's requirement to retain real observation timestamps. Expiry uses wall time, but runs every scheduler tick rather than hourly.
- No durable reset generation prevents delete/expiry and re-consent races. Plan/graph expected versions are absent from commit inputs. HTTP responses now declare LearningView/transcription models; lifecycle and version envelopes remain proposed.
- Store request outcomes retain full snapshots in the jobs table without a bounded cache; C owns its replacement. Current events are append-only in logical use, but relational constraints, replay and ordered source/notification queries need C's work.

Treat these as implementation tickets, not shipped capabilities. This document defines the handoff plan, not a schema migration already applied.

## Current contracts and transport

Pydantic models in `shared/contracts/loke_contracts/models.py` are the schema source of truth and forbid extra fields. `ContractBundle` is the export root. Types derive from `npm run contracts:generate`; never hand-edit generated output. Add new public models to the export root or exporter so they appear in TypeScript, and add route response models so OpenAPI reflects the actual API.

| Current model | Fields and limits that consumers must preserve |
| --- | --- |
| `GoalInput` | request_id (1 to 100 chars), goal (3 to 500), storage_consent, reminders_enabled default true, study_minutes default 10 (3 to 30) |
| `LearningInput` | request_id, text (1 to 15,000), mode text/voice/attachment; voice means a confirmed transcript |
| `AnswerInput` | request_id, card_id, answer (1 to 200) |
| `EvidenceEvent` | id, nullable concept/card/expected_answer/grader, kind study_report/quiz_answer, text, occurred_at, assessment not_assessed/correct/incorrect/ungraded, assistance none/after_explanation, source text/voice/attachment/quiz |
| `NextActivity` | kind diagnostic/practice/review/learn, concept_id, title, reason, reason_event_ids, minutes |
| `QuizCard` | id, concept_id, kind mcq/blank, prompt, options; no answer key |
| `ContextBundle` | learner/agent/goal, state/plan revisions, concepts, states, events and sources |
| `TopicProposal` | nullable concept_id, explanation capped at 800 chars |
| `Notification`, `SourceChunk` | Notification has id/title/reason_event_id/created_at; chunk has source_id/title/text. Current source_id combines a text hash and chunk index. |
| `LearningView` | learner/agent/goal/consent/reminders, state/plan revisions, model_mode, demo_clock_hours, response, plan, active_quiz, states, concepts, events, notifications, sources |

Current routes: GET `/api/view`; POST `/api/goal`, `/api/input`, `/api/quiz/answer`, `/api/reminders`, `/api/demo/clock`, `/api/audio/transcribe`; DELETE `/api/learner`. Learning mutations return LearningView except transcription, which returns `{text, provenance: "audio_transcription", saved: false}`. The [input README](../input/README.md#current-http-and-schema-baseline) lists exact payloads and errors. There is no separate notifications GET route: the view carries notifications.

Learner identity is selected in the server, not submitted by the renderer/model. Keep the local proxy token server-side. Domain failures currently return 400, auth 403, revision/request reuse conflicts 409, Pydantic validation 422 and provider failures 502. Do not invent multi-user authentication, public hosting or a new transport for the demo.

## Shared extension proposal, not implemented yet

Publish this small agreed contract slice before dependent implementation. The names below are a proposed common design for A/B/C to adopt together. Until generated types, API fixtures and memory support land, the current models/routes above remain authoritative. Any change to this proposal must be communicated to both consumers, not independently guessed in a layer.

### 1. Identity, versions and commits

- Add an opaque `generation_id` to stored learner state, LearningView, context and all learner writes. C issues/persists the generation and rotates it atomically on delete/expiry. Empty-view reads must return a stable reset generation without creating consented history. A compares generation first, then monotonically increasing revisions within it. C may need a minimal non-content reset marker; define its retention explicitly so deletion never leaves learning content in a tombstone.
- Add `expected_state_revision` to ordinary writes and `expected_plan_revision` to activity/attempt writes. Slow proposals also capture `graph_version` and generation. C atomically validates relevant base versions, consent and subject-agent identity before commit. Avoid holding locks/transactions during provider calls.
- Preserve successful duplicate semantics: learner/generation/operation/request ID scopes a canonical fingerprint. Identical replay returns the stored outcome without new events, revisions, jobs or provider calls. Same key with different payload gives 409. A network retry reuses the exact ID and payload; a confirmed conflict reloads current state before a new user-confirmed operation. C supplies preflight outcome lookup, but commit remains the authoritative dedupe check for concurrent requests.
- Create typed `MemorySnapshot`, commit command/result and shared conflict types. Initially a typed wrapper around the existing mutate path is sufficient. Include goal/budget/consent, generation, versions, agent, states/events/sources/plan, quiz session, assistance exposures, review jobs and notification state. Add `learner_ids` and bounded referenced-evidence reads to MemoryPort. Name and type the legacy callback explicitly if it remains during transition; do not rewrite the store in B.
- `state_revision` increments for an actual durable learner change; `plan_revision` increments only for a changed plan/activity state. Reads and failed/no-op dispatches increment neither. Define atomic no-op outcomes with C. Dates use timezone-aware UTC. Real evidence observation and retention timestamps use wall time; only eligibility/deadline simulation uses an injected review clock. Store clock mode/capability in the view so A can hide unavailable controls.

### 2. Activities and a single quiz attempt

- Extend NextActivity with stable `activity_id`, nullable `card_id`, status pending/in_progress/completed/skipped, `reason_code`, `reason_event_ids`, `prerequisite_ids`, optional typed edge IDs and nullable due time. Plan revision is the version, not the activity identity. Preserve IDs for surviving activities; generate new IDs for replacements. A renders server status and does not manufacture completion.
- Introduce `QuizSession`: attempt_id, activity_id, card_id, started_at, nullable ended_at, status in_progress/completed/cancelled and assistance exposure references. An offered QuizCard remains distinct from a started session. At most one in_progress attempt exists per learner/generation across modes.
- Proposed POST `/api/quiz/begin`: request_id, generation_id, expected state/plan revisions, activity_id and card_id. POST `/api/quiz/cancel`: the same version envelope plus attempt_id. Extend answer with attempt_id and the version envelope. Begin/cancel/answer return committed LearningView. Ungraded answers append traceable ungraded evidence but keep the attempt open; valid graded answers close it atomically. Reject stale/closed/mismatched attempts without an additional graded event.
- Proposed POST `/api/activity/complete`: version envelope plus activity_id, for learn activities. Completion records participation/plan progress, never correct-answer evidence or mastery. Quiz activities complete only through graded answer. Do not add this action by overloading `LearningInput.text` with hidden command strings.
- Reports may add evidence/sources during a quiz but must not replace the in-progress attempt. Queue subsequent selection until attempt completion/cancel. Assistance must record relevant explanation exposure per session/concept and carry across immediate practice. A later independently started review can be unassisted only under an explicit reset rule tested by B, not merely by reloading the UI or changing cards.

### 3. Notifications and snooze

- Extend Notification with concept_id, review_job_id, status unread/read/dismissed, nullable read_at and snoozed_until. Keep reason_event_id. C stores job due/lease/status separately from notification display state.
- Proposed POST `/api/notifications/action`: request/version envelope, notification_id, action read/dismiss/snooze/begin_review and optional snooze_hours. For the MVP, snooze_hours is a bounded integer 1 to 168, accepted only for snooze. Server computes the deadline with the appropriate review clock. Return LearningView. Begin_review validates eligibility and starts an attempt on the referenced review activity atomically; if another quiz is active, reject rather than interrupt it.
- Read affects display status, dismiss hides that notification, and neither changes learning evidence or erases the future review requirement. Snooze postpones delivery/eligibility until a durable deadline without changing assessment history. It must not immediately regenerate the same notification. Keep a stable dispatch dedupe key, and define redisplay of the existing notification after snooze rather than creating duplicates.
- Add request/generation/version fields to reminder settings and clock writes; extend delete with a generation-aware write envelope through a coordinated proxy/API change. Keep the view polling route rather than adding redundant polling APIs.

### 4. Graph, context, provenance and errors

- C publishes a versioned reviewed graph with distinct prerequisite_of/related_to edges and stable edge IDs. Catalog `Concept.prerequisites` currently points from a dependent to its prerequisites; any prerequisite_of edge points from prerequisite to dependent. Make direction explicit and validate acyclicity. No inferred/model edge enters the reviewed graph automatically.
- Extend context with graph_version, needed edges, pending activity/quiz, budget/preferences, generation and bounded relevant evidence. Retain ten recent events plus a separately bounded set of referenced reason events, at most two retrieved chunks and a measured prompt budget. C supplies actual chunk/provenance IDs and hashes; do not rename current source_id and lose existing citations without a migration/adapter.
- Extend TopicProposal with clarification/uncertainty and supporting source/chunk/evidence IDs from the supplied context. Model output cannot include grades, state mutations, identity or schedules. Validate every citation against retrieved context; reviewed URLs come from catalog resources, never arbitrary generated strings. Add a bounded evidence lookup route or bounded `reason_events` in LearningView so A can resolve old reason references without retrieving lifetime history. Prefer the view extension for the six-concept MVP.
- Publish a stable error envelope with safe detail and an error code, separating version conflict, payload reuse, inactive attempt, missing consent, unsupported media and provider failure. Preserve status semantics and let A recover from validation arrays during migration. Include response models for LearningView, transcription and errors in OpenAPI.

### Contract change protocol

For each slice, B publishes Python models/ports, generated artifacts and valid request/success/error examples. A reviews action/render semantics and updates its proxy/types/adapter; C reviews transaction/generation/migration semantics and supplies a fake implementation plus persistence support. Merge an additive adapter first where feasible; required new fields need coordinated consumers and migration defaults. Old records must load or fail with an explicit migration instruction, never through silent JSON reinterpretation. Do not implement all proposed extensions in one breaking change.

## Work sequence and definition of done

### B0: freeze contracts and unblock teammates, first hour

Published baseline: [v1 fixtures and integration guide](../../shared/fixtures/README.md), generated
contracts, OpenAPI response models, and `tests/fakes.py` (database-free MemoryPort). A can consume
the current screen/error cases; C can exercise commit/dedupe/rollback semantics. No proposed
lifecycle/reset/notification extension has been accepted or implemented by this baseline slice.

Publish a minimal current-contract fixture pack under `shared/fixtures/`: empty view, saved goal, wrong answer with prerequisite reason, ungraded answer, assisted correct, sources, due reminder, reset and errors. Use stable fixture IDs from the reviewed catalog, timezone-aware timestamps and real cross-references. Keep future extension fixtures separately versioned until their schema exists. Validate fixtures through Pydantic; A consumes generated types, C verifies port behavior.

Resolve lifecycle/reset/notification shapes with A/C and record the exact accepted slice in this README. Add the missing scheduler enumeration to MemoryPort immediately as a narrow fix. Build coordinator tests against a typed fake while C migrates. No fixture endpoint may write production state or imply an unavailable provider succeeded.

Done: A can build all current screens without waiting for C or a live model, C has explicit commit semantics, and all three owners know the first integration slice.

### B1: assessment, association and plan policy

Keep curated MCQ/blank grading in code. Normalize only documented answers/aliases. Unknown free-form responses remain ungraded with clarification. Preserve observed answer, expected answer after assessment, grader version, assistance, provenance and server timestamp. Reading/reporting/attaching/transcribing cannot mark a concept assessed.

Implement alias matching with token boundaries and deterministic ranking; tied or insufficient matches return uncertainty instead of arbitrary first match. Live interpretation is optional and bounded to known candidates. Use the reviewed graph only, depth-two traversal and a fixed tie order. Select due review, nearest unchecked prerequisite of a missed item, missed-item practice, remaining goal prerequisites, then next goal concept. Already attempted activities should not loop endlessly in the same plan. Honor budget and availability, retain stable activity IDs, and permit completed/empty plans rather than fabricating three endless steps.

Use +24 hours for incorrect/conservative assisted practice and +72 for unassisted correct. An assisted retry must not move an earlier due deadline later. Clarify assistance reset across independent review sessions. Ungraded answers produce no correctness projection or review extension. A meaningful event can replan; polling and empty ticks cannot. Preserve the active attempt while choosing a pending next action.

Done: deterministic tests cover incorrect/prerequisite, missing evidence, correct/assisted/ungraded, ties, traversal depth/cycles, plan budget, completed activities and no-op revisions. Every reason refers to stored evidence/known prerequisite IDs.

### B2: authoritative commits and reset safety, joint slice with C

Compose evidence append, projection update, activity/attempt state, plan revision, stale-job cancellation and replacement review in one atomic commit. Do not set final UI revisions before persistence succeeds. C owns SQL/migrations/replay and outcome caching; B supplies the deterministic decision and base versions. Identity/consent/generation checks occur at the commit boundary even if preflight already passed.

Test slow proposals against concurrent goal change, clock change, graph change, delete and delete followed by re-consent. Old generation work must never recreate deleted events/sources or apply to the new agent. Retry before provider execution using cached outcomes when available, and bound concurrent identical requests so dedupe does not cause duplicate paid calls. Protect agent uniqueness through C's learner/subject constraint, not only a Python `or uuid4()`.

Done: one request yields one outcome, payload reuse conflicts, stale work commits nothing, restart preserves agent and plan, generation reset blocks old actions, and synthetic learners cannot read each other's evidence/sources/jobs.

### B3: scheduler, quiz suppression and durable notification actions

Use an injectable UTC review clock; test it rather than sleeping for a day. Fix shifted evidence timestamps before relying on new fixtures. Scheduler continues every 30 seconds in normal mode; cleanup runs on its own hourly cadence. Catch overdue jobs after startup. No background model calls, no claim of delivery while backend is stopped.

Inside the dispatch transaction, recheck storage/reminder consent, generation, current job status/due/snooze, latest reason evidence, active attempt and the one-unsolicited-reminder-per-24-hours cap. Order candidates by due time and stable ID. An offered card does not suppress; a started attempt does. Newer evidence cancels/replaces stale jobs and stale unread notification eligibility. Plan revision changes only if the available plan changes. Snoozed reminders wait until their stored deadline; reading/dismissing cannot create repeated alerts.

C supplies atomic claim/lease and uniqueness when extending beyond the single-worker scaffold. Do not claim multi-worker safety until SQLite/PostgreSQL behavior has been checked under that configuration. One notification row per dispatch key survives polling/restart. A consumes the committed actions described above.

Done: due job emits once; disabled consent/reminders, active attempt, snooze and stale evidence block delivery; cancel/complete and restart resume eligible delivery; cap and duplicate concurrent ticks hold; empty/no-op ticks do not mutate revisions.

### B4: bounded explanations, sources and audio

Keep demo mode deterministic and free of provider requests. In live mode use at most one interpretation plus one explanation call, 15-second timeout each, allowed provider routing and strict schema validation. The current one-call design is sufficient unless a second call is needed. Keep the whole request within the proxy's 35-second timeout or change the proxy deadline with A. Enforce the shared testing cap of 50 model-backed turns and ten audio clips with a $30 ceiling for team testing; do not silently add retries or a new provider stack.

Retrieve learner-scoped context, ten recent events, bounded supporting evidence and at most two matching chunks. Set a measured context budget, trim rather than loading lifetime history, and do not trigger automatic topic splitting. Empty retrieval yields an honest no-source path. Treat source instructions as data. Validate known concept/citation IDs and resource URLs. On timeout, malformed/unknown proposal or provider failure, retain a deterministic reviewed response or request clarification; never synthesize evidence. Decide the fallback before the single commit so the report is not written twice.

Audio remains a separate unsaved preprocessing route: explicit audio disclosure and storage consent, bounded bytes plus server media/duration validation, safe timeout, no raw-media retention, no transcript commit before A's explicit Send. A already stops recordings at 30 seconds; choose and publish the same duration cap for uploaded audio and server enforcement. Reject unsupported/empty/invalid media with text fallback. Do not infer MIME truth from the extension alone or upload through a persistent Files API. Avoid content/provider secrets in logs. Provider retention differs from local deletion; UI wording must stay accurate.

Done: demo loop works offline from paid providers; live adapter tests use fakes for errors/citations; optional actual provider smoke tests are reported separately. Audio failure never claims successful transcription, never writes a report and never prevents text input.

## Parallel delivery and checkpoints

| Deliverable | B supplies | A and C can proceed with |
| --- | --- | --- |
| Baseline fixtures and HTTP inventory, first hour | Typed current examples, error cases, missing-field inventory | A builds screens/adapter; C tests current memory behavior |
| First contract slice | Generation/version and quiz/activity schemas, examples and port semantics | A builds session controls; C persists reset/session/atomic transitions |
| Reminder slice | Eligibility rules, action schema, deterministic clock fixtures | A builds notification actions; C adds due/lease/snooze persistence |
| Provenance slice | Context/citation validation and bounded reason evidence | A builds evidence/source UI; C supplies graph/chunk/lookup data |
| Integration proof | Coordinator/API behavior checks and exact acceptance results | All run real UI/backend/store flow and rehearse |

Do not make A wait for a complete live agent or C wait for final planner wording. Keep dependencies narrow with a fake port and generated fixture views. B coordinates integration; C reserves three hours, roughly one with A on source/quiz data and two with B on commits/scheduler. A owns final common visual/keyboard pass. Report a blocker as an exact missing contract/operation plus a temporary fixture adapter and independent work to continue.

Use about 15 hours including integration. Shared October 17 and 18, 2026 checkpoints in Asia/Shanghai: Saturday noon real goal/agent/plan persistence; 15:00 wrong-answer/prerequisite/revision loop; 19:00 desktop/source/restart/reminder loop; Sunday 11:00 polish, 13:00 freeze and two timed rehearsals. Contract publication and deterministic correctness precede richer prompts.

## Verification and final handoff

Run setup from the repository root: `uv sync`, `npm install`, `npm run contracts:generate`. Demo startup uses `npm run dev` or `npm run desktop`. Keep `MODEL_MODE=demo` for core checks. PostgreSQL needs Docker and its own explicit database URL; switching from SQLite does not migrate learner data.

After each integrated contract slice, run the relevant behavioral tests and typecheck. Final shared checks:

```sh
npm run check
npm run build
uv run ruff check .
```

Add meaningful tests for the missing behaviors above to the shared suite with coordinated ownership. Existing tests cover consent/auth, wrong-answer/dedupe, ungraded/stale card, durable reminder, attachment/delete, restart/isolation, stale model after goal change, import boundary, reminders off, assisted deadline and provider failure with no fabricated event. They do not prove lifecycle, leases, snooze, graph versions, reset generations, real PostgreSQL, native audio or live provider behavior. Once fallback behavior changes, update the provider-failure test to assert the accepted deterministic outcome and absence of fabricated assessment.

Deliver changed-file/contract/migration notes, tests passed, exact unresolved limitations and a real-flow result. Verify schema generation produces no unexplained diff, OpenAPI matches routes, and A's proxy allowlist matches new paths. Record PostgreSQL/live/native checks as unverified if unavailable. No push or commit unless the teammate explicitly asks.

Cut automatic topic splitting, recursive agents, arbitrary subjects, generated images/video, phone/SMS, embeddings/vector databases and packaged distribution first. Preserve atomic learning turns, traceable reasons, restart identity, consent/reset safety, active-quiz suppression and one durable review. Keep this handoff aligned with the implemented contract after each slice instead of leaving proposed fields looking shipped.

## Layer C integration update

The approved memory slice now uses PostgreSQL only. Coordinator goal/input/answer accept optional
ChatScope and generation/version envelopes, explicitly retrieve agent memories across chats and
record committed conversations/actions atomically with learning turns. The shared source models
live in loke_contracts.source; the intelligence source_models module re-exports them.

C supplies reset generations, bounded replay outcomes, document/graph persistence, typed context,
category log trees and leased maintenance. The scheduler rechecks review eligibility within the
learner transaction and runs memory maintenance/cleanup on separate cadences. New evidence uses
wall time and carries explicit projection-after data for B's replay reducer. Older audited gap
items above describing bootstrap storage, unbounded outcomes, shifted observation timestamps or
missing reset generations are superseded by this slice.

Quiz-session lifecycle, notification actions, generic source-category HTTP execution and UI chat
identity wiring remain B/A integration. The existing dictionary transform is now an explicitly
typed transitional wrapper; it has not been replaced by a generic agent framework. See
../../docs/MEMORY_OPERATIONS.md for exact contracts and limits.
