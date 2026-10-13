# A: input and experience implementation handoff

## Your persona and outcome

Act as the frontend and desktop experience owner. Build a clear, accessible learning workspace that submits typed learner actions and renders committed backend decisions. Own interaction design, recording, attachments, error recovery and Electron boundaries. Do not implement a second grader, planner, scheduler or learner database in the client.

This is the handoff to give your coding agent. Read [the intelligence handoff](../intelligence/README.md) for the shared extension proposal before changing an interface. A owns input, B owns intelligence and Python contracts, and C owns memory, migrations and the reviewed catalog. These are logical layers of one application.

The demo must show: consent and goal, a persistent subject agent and short plan, a confirmed study report, an incorrect quiz answer, an automatically selected prerequisite, a revised plan, an attached note with honest provenance, restart persistence and one scheduled review. The product claims item evidence and useful next steps, not validated mastery or measured forgetting.

## Scope and file ownership

| Area | Owner and rule |
| --- | --- |
| `web/app/page.tsx`, `globals.css`, `layout.tsx` and extracted UI modules | A owns final UI, component composition, local form state and visual tokens. Extract components/hooks as needed inside input. |
| `web/app/api/backend/[...path]/route.ts` | A owns the authenticated, allowlisted proxy. Update it in the same integration slice as a new backend route. |
| `desktop/main.cjs` and desktop package | A owns the local window, media permissions and external navigation restrictions. |
| `shared/contracts/loke_contracts/models.py`, `ports.py` | B owns contract publication with A/C review for their boundaries. Consume generated TypeScript, never edit generated files. |
| `shared/contracts/loke_contracts/catalog.py`, memory implementation | C owns reviewed concepts/cards, storage, retrieval and migrations. No catalog or answer-key copies in the renderer. |
| Root launcher/config/dependencies and `tests/test_learning_loop.py` | Shared integration surfaces. Coordinate an exact change with its owner; avoid unrelated formatting and dependency churn. |

A may add UI fixtures in `web/` immediately. B publishes shared fixtures under the currently empty `shared/fixtures/` extension point. C supplies a memory fake. Each owner maintains their own README; B maintains the common contract proposal in the intelligence README. Do not silently change another layer to make a mock pass.

## What is implemented today

The app has Today/Study/Concepts, goal consent, a three-item plan, MCQ/blank submission, text and Markdown input, editable voice transcripts, a reviewed SVG, textbook links, reminder toggle, deletion and two-second view polling. Electron uses a sandboxed renderer with Node disabled and context isolation enabled. Default demo mode needs no provider key; transcription always needs direct OpenAI access.

Current gaps to fix:

- Today and Study mostly render the same content. Plan rows cannot start or complete a particular activity.
- `active_quiz` currently means an offered card, not a durable learner-started attempt. There is no begin/cancel API. Do not infer reminder suppression from this field.
- Notifications are display-only; no read, dismiss, snooze or begin-review action exists.
- The UI creates a new request ID on every submission. Reliable retries need a stable ID and frozen payload for the same operation.
- The revision guard cannot distinguish deletion/expiry and re-consent from ordinary older responses. Deletion manually clears the reference but in-flight polling can restore deleted data.
- Recording has a 30-second timer, but unmount cleanup stops tracks without a complete recorder/request cancellation lifecycle. Recording size is not bounded as chunks arrive.
- The proxy assumes error detail is a string; FastAPI validation can return an array. Recording/transcription/saving also share one generic busy label.
- Reasons show a generic evidence chip rather than inspectable event references. Displayed source chunks are not validated explanation citations.
- Electron permission checks use a URL prefix. Replace this with parsed exact-origin checks and validate navigation consistently.

The specification describes future fields absent from generated types. Do not ship renderer casts, invented endpoints or hardcoded session IDs to bridge these gaps.

## Current HTTP and schema baseline

Renderer requests use `/api/backend/<path>`. The Next.js server forwards to FastAPI `/api/<path>` and injects `x-loke-session`. The learner is selected server-side by `DEMO_LEARNER_ID`; client payloads do not select a learner.

| Method and path suffix | Current request | Current success |
| --- | --- | --- |
| `GET view` | None | `LearningView` |
| `POST goal` | `GoalInput`: request_id, goal, storage_consent, reminders_enabled, study_minutes | `LearningView` |
| `POST input` | `LearningInput`: request_id, text, mode | `LearningView` |
| `POST quiz/answer` | `AnswerInput`: request_id, card_id, answer | `LearningView` |
| `POST reminders` | `ReminderSettings`: enabled | `LearningView` |
| `POST demo/clock` | `ClockAdvance`: hours | `LearningView` |
| `DELETE learner` | None | Empty `LearningView` |
| `POST audio/transcribe` | Multipart field `file`, header `audio-consent: true` | `{text, provenance: "audio_transcription", saved: false}` |

Only goal, input and answer currently carry dedupe IDs. Settings and clock are not retry-safe through a client request ID. HTTP errors currently use `{detail}`: 400 for domain errors, 403 for auth, 409 for memory conflicts, 422 for validation, 502 for OpenRouter/proxy failures. Normalize string and array validation details for display. Never expose raw provider messages or secrets.

Important limits: goal 3 to 500 characters, study budget 3 to 30 minutes, report 1 to 15,000 characters, answer 1 to 200 characters, request ID 1 to 100 characters. Audio is rejected above 1,000,000 bytes; supported suffixes are MP3, MP4, M4A, WAV and WebM. Text/Markdown attachments have the same client byte limit and a 15,000-character extracted-text limit. The report API receives text, not the original attachment filename or a binary document.

`LearningView` carries agent_id, state_revision, plan_revision, consent/reminder flags, response, plan, active_quiz, concepts/states, the last ten events, sources and notifications. Dates arrive as JSON strings. Missing concept state means not checked. `QuizCard` contains prompt/options but no answer key. Plan entries have no activity IDs, completion state or graph-edge references yet. Use generated `@loke/contracts` types; a fixture must satisfy the same type as a real response.

For planned endpoints, generation/reset handling, quiz sessions, activity IDs and notification actions, use the single [shared extension proposal](../intelligence/README.md#shared-extension-proposal-not-implemented-yet). This section is the current baseline, not permission to treat proposed APIs as available.

## Work sequence and acceptance

### A0: independent foundation and fixtures, first hour

Read current models, both handoffs, [ownership](../../docs/HORIZONTAL_OWNERSHIP.md) and [weekend specification](../../WEEKEND_MVP_PLAN.md). Start the current browser loop, then Electron. Preserve the existing working path while extracting an API adapter, response reducer, recording hook and focused UI components. Do not add a global state framework or change stacks for this MVP.

Build typed fixture states for empty/consent, saved goal, wrong answer/prerequisite, ungraded answer, assisted correct, due reminder, sources, offline/error and reset. Add planned states only after B publishes their generated contracts. Ensure the wrong-answer fixture references a real event and known concept; no frontend-generated learner evidence. Local fixture mode must be visibly a development aid and must not make real writes.

Acceptance: the current UI compiles, core fixture states render, and API-dependent controls can be developed through the adapter while B/C work. Send B the exact fields needed for activities, quiz lifecycle and notifications immediately.

### A1: committed actions and response ordering

Keep a per-operation request ID and exact payload until its outcome is known. For a timeout or disconnect, retry the same ID/payload. For a confirmed revision conflict, reload and ask the learner to resubmit the intended action with a new ID after reviewing current state. Never silently resend an answer to a different card. Polling remains a read only, with no model or plan mutation.

Apply committed responses by generation and revision once the proposed reset contract exists. Before it exists, capture a local reset/request generation for every async operation, invalidate it on delete and ignore older callbacks. Abort reads/transcription on unmount/reset, prevent overlapping polls, preserve drafts and focused controls during polling, and do not clear a draft solely because a cached response was rejected as stale. Discard response bodies from an obsolete generation even if their numeric revisions are larger. Handle backend expiry as a reset when consent/agent disappear; do not automatically re-consent or replay a pending write.

Disable duplicate writes while one is pending. Show saving, transcribing, offline and retry states separately. Failed save preserves the draft. Failed audio processing preserves useful existing text. Do not claim saved until the backend commit succeeds. Error recovery must leave the user able to type.

Acceptance: delayed poll/write replies cannot roll back a newer view or restore deleted history; a network retry cannot duplicate evidence; validation errors render human-readable text.

### A2: activities and quiz lifecycle, joint slice with B/C

Implement explicit Start and Cancel controls using the published session contract. An offered quiz does not count as an active attempt. Send attempt/activity IDs and expected versions rather than card ID alone. Reset answer state by attempt identity, since the same card can recur in a later attempt. Complete an explanation activity through a server action that advances the plan without marking mastery. Do not mark a quiz complete locally before the answer commits.

One question may be in progress across all input modes. Reports, recordings and attachments must not replace an in-progress answer. While B has not supplied lifecycle routes, retain the current answer flow and keep lifecycle controls behind the development adapter.

Acceptance: Start persists an attempt, due reminders pause during it, Cancel resumes eligibility, valid answer closes it, ungraded answer keeps it open, and polling preserves the selected answer and focus. A later attempt on the same card has a fresh answer field.

### A3: input, transcript and attachment lifecycle

Use recording states idle, requesting permission, recording, stopping, transcribing and editable draft. Check supported recorder MIME types before selecting a format; send a filename consistent with the actual recording MIME type. Stop at 30 seconds and stop early at the byte cap. Release all tracks, timers, handlers and blobs on success, failure, cancellation, unmount, consent revocation and deletion. An unmount/cancelled recording must not invoke transcription from a late `onstop` callback. Check generation/consent again before a late permission grant or transcription result is applied.

Show audio disclosure before transmission. Permit explicit cancel/discard. Never commit a transcript automatically: successful transcription only fills an editable draft; Send uses `mode: "voice"`. Notes use `mode: "attachment"`; reading/uploading adds report/source provenance, not a grade. Unsupported files and over-limit content get recoverable errors. Render learner/provider/source text as escaped text; do not insert raw Markdown HTML or arbitrary SVG.

Acceptance: denied permission, empty clip, bad format, oversized clip, provider failure, route change and delete during recording/transcription all release resources and leave text input usable. No key is needed for the text-only rehearsal.

### A4: reminders, evidence and final design

Add begin-review, read, dismiss and snooze controls only for committed notification contracts. Snooze is a persisted server deadline, not a browser timeout. Reminder opt-out takes effect server-side. Two-second polling reads durable notification state; it never emits a fresh desktop notification on each refresh. Keep in-app reminders as the requirement; OS notifications are optional after acceptance.

Today shows the goal, three-step plan and one primary next action. Study focuses on the current activity, feedback and report composer. Concepts shows reviewed dependencies and narrow evidence labels. The right panel explains Why this next, lets the learner inspect referenced events, and identifies uploaded-note excerpts separately from reviewed textbook resources. Because only ten events are returned, B must provide bounded referenced evidence lookup when a reason points to an older event. Do not fabricate the missing excerpt. Cite sources as explanation support only when B supplies validated citation IDs.

Preserve the restrained Apple-like direction: pale gray background, white surfaces, dark text, blue action color, system fonts, generous consistent spacing, restrained corners and a narrow sidebar. The current CSS already adjusts the specification's blue/muted colors; centralize existing tokens and verify contrast before changing them. Aim for 28px headings, 16px body, 13px secondary text and an 8px spacing rhythm. Fix the current abundance of 10px/11px text where readability suffers. Prioritize one activity over a wall of cards. The reviewed SVG is a simplified teaching sequence, not the full prerequisite graph.

Maintain labels, visible focus, keyboard radio groups, accurate status announcements and non-color correctness cues. Use reduced-motion preferences. Keep focus stable after polling; move it intentionally after submitted feedback or a new attempt. Verify Electron at its 900 by 700 minimum and browser narrow layouts. Do not expose provider keys, internal wiring or fixture controls in the ordinary learner flow. A demo clock must be visibly labeled wherever its shifted deadlines are shown and unavailable in normal mode once B exposes capability metadata.

Acceptance: goal and quiz work by keyboard, reasons are traceable, reminders act on durable state, no content overflows at target sizes, and the four-to-five-minute demo is understandable without developer narration.

## Dependencies and parallel work agreement

| Need | Supplier | A can do while waiting |
| --- | --- | --- |
| Current LearningView fixtures | B publishes canonical examples; A may create local typed examples now | Component extraction, design, API reducer and keyboard work |
| Quiz/activity session contract | B defines lifecycle; C persists it | Controls against typed fixture adapter, no fake production routes |
| Snooze/read/dismiss schema | B defines eligibility; C implements durable mutations | Reminder component and error/loading states |
| Reset identity and referenced evidence | B publishes HTTP/view contract; C persists generation and lookup | Local generation cancellation and evidence panel shells |
| Source provenance and citations | C provides scoped chunks; B validates proposal citations | Safe text rendering, upload limits and separate source/resource views |

B publishes the schema and fixtures before implementing every feature. A publishes the UI state/action inventory before polishing. C can adapt storage behind the current MemoryPort while the new port is negotiated. Share small vertical integration slices, not a final large handoff. Any shared contract change includes generated artifacts, adapter updates, fixture updates and a named migration owner. Do not wait for PostgreSQL or paid providers to implement the demo-mode UI.

## Setup, verification and handoff evidence

From the repository root:

```sh
cp .env.example .env
uv sync
npm install
npm run contracts:generate
npm run dev
# In a separate run, use npm run desktop instead of npm run dev.
```

Keep keys and `SESSION_TOKEN` in server environment variables, never `NEXT_PUBLIC_*`, renderer code, screenshots or logs. The same UI/proxy runs in browser and Electron. Keep Node disabled, context isolation and sandbox enabled. Allow only the exact local application origin for media/navigation and HTTPS hosts in the reviewed resource allowlist for external links. Avoid arbitrary IPC, filesystem access or package/signing work.

Before handoff, run `npm run typecheck`, `npm run build` and the shared `npm run check` once contracts are integrated. Use focused UI interaction checks for ordering/reset/recording behavior and manual keyboard/desktop checks; do not add snapshot tests for every cosmetic edit. Verify the real UI/backend/store loop, not just fixtures.

Deliver a concise report listing changed files, contract assumptions, checks passed and remaining blockers. Include actual proof of: goal/agent survive restart, wrong answer changes the prerequisite plan, duplicate retry does not duplicate evidence, transcript requires confirmation, deletion ignores late responses and one due reminder appears after quiz end. Record unsupported native/audio cases as failures with the working text/browser fallback, never as passes. Do not commit or push unless the teammate explicitly asks.

## Schedule and scope cuts

Budget about 15 hours including integration. Use the shared October 17 and 18, 2026 schedule in Asia/Shanghai: first-hour contract/fixture alignment, Saturday noon persisted goal/plan UI, 15:00 quiz/prerequisite loop, 19:00 complete desktop/reminder loop, Sunday 11:00 visual/keyboard pass, 13:00 feature freeze and two timed rehearsals. Reserve roughly three hours for real integration and rehearsal rather than using the full budget for layout.

Cut OS notifications, arbitrary binary attachments, media generation, phone/SMS, automatic topic splitting and packaging first. Preserve correct commits, reset handling, editable transcript, active-quiz/reminder behavior and the primary learning flow. A blocked dependency must be reported with its exact missing shape and fixture; continue independent UI work.
