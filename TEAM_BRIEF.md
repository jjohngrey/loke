# Loke: desktop MVP and team split brief

Full specification: [WEEKEND_MVP_PLAN.md](WEEKEND_MVP_PLAN.md). Horizontal ownership is selected. A runnable starter scaffold is in place; remaining MVP work is listed in the layer README files and docs/HORIZONTAL_OWNERSHIP.md.

## Product and demo

Desktop is the primary MVP. SMS is a possible reminder layer later; native iMessage, direct calls, smart glasses and VR are deferred.

The neuroscience demo covers neural signaling. A learner sets a goal, reports studying by text/voice, answers a quiz, receives a revised plan and a prerequisite check without asking what next, then gets a timed review reminder. Their evidence and plan survive restart.

The differentiator we can demonstrate is proactive activity selection with traceable evidence. We cannot establish validated mastery, measured forgetting or general discovery of unknown knowledge from this weekend demo.

## Shared architecture

| Layer | Responsibility |
| --- | --- |
| Input/experience | Electron desktop window; Next.js UI/proxy; text, microphone, attachments; quiz/explanation/diagram/resources; notification controls |
| Intelligence | FastAPI interaction/topic agents; concept association; prerequisite checks; deterministic grades and next activities; plan updates; review eligibility |
| Backend memory | PostgreSQL graph, immutable evidence, current projections, source chunks, plans and durable jobs; scoped retrieval/atomic commits |

These are logical layers in one backend application, not separate microservices. OpenRouter handles text interpretation/explanation; direct OpenAI handles file transcription. API keys remain server-side.

Reuse OpenPoke's Next.js/FastAPI foundations, OpenRouter plumbing, role/history organization and scheduler structure from a pinned snapshot. Retain notices. Replace Gmail tools, email watchers, unrestricted loops and full-history context with learning contracts. No Composio/Gmail account is needed.

## Core intelligence decisions

- Six reviewed concept nodes and typed prerequisite/related edges, eight quiz cards, one subject execution agent.
- Input association uses canonical aliases and bounded token similarity. Similarity does not prove a prerequisite or learner knowledge.
- Reports, quiz answers and model hypotheses remain distinct. Current state is a versioned projection of timestamped events, not one growing summary blob.
- Commit event/state/plan/review atomically. Dedupe request IDs and check state/plan/graph versions before applying a slow model proposal. UI rejects old revisions.
- Select due review first, then an unchecked prerequisite of a missed item, missed-item practice, remaining goal prerequisites, and the next goal concept. Reasons include real event and graph IDs.
- Missing evidence means “not checked yet,” followed by a diagnostic. It does not mean the learner has a proven hidden gap.
- Initial plan has three activities inside a ten-minute budget; update on meaningful events, not UI polling or every scheduler tick.
- Reviews use explicit +24-hour missed and +72-hour unassisted-correct heuristics. Assistance/uncertainty is conservative; due means scheduled practice, not measured forgetting.
- Scheduler creates one durable, deduplicated, opt-in reminder, rechecking current evidence/consent and pausing during learner-started quizzes. In-app reminders require a running backend; overdue jobs resume on startup.

Topic-agent splitting is a later bounded mechanism. Context budget and separable subtopics can trigger a proposal, with shared canonical evidence and parent routing. No recursive spawning or copied divergent histories. Demo needs one root; at most two manually approved children are optional.

## Selected: horizontal layer ownership

| Member | Owns | Main handoff |
| --- | --- | --- |
| A | Electron/Next.js/UI, recording/upload and quiz controls, visual polish | Emits LearningInput, renders LearningView |
| B | Coordinator/topic logic, grading, prerequisites, plan policy and reminder decisions | Produces EvidenceEvent/NextActivity; consumes store/context contracts |
| C | Database/graph/evidence projections, retrieval, job persistence and cleanup | Provides load_context/commit_learning_turn/claim_due_review |

Fits specialist skills. Main risk is B becoming the bottleneck and three working layers failing to form a learner flow. Fixtures by the first hour and real whole-flow checkpoints at noon, 15:00 and 19:00 are required. Budget 15 hours each, with C reserving three hours for integration support.

## Archived comparison: vertical feature ownership

| Member | Owns across all three layers | Demonstrable outcome |
| --- | --- | --- |
| A | Goal/Today UI, goal/topic-agent logic and plan persistence | Goal → reusable agent → reasoned study plan → reload |
| B | Quiz/reminder UI, assessment/adaptation policy and evidence/state/jobs | Answer → evidence → revised plan → automatic review notification |
| C | Voice/attachment/knowledge UI, concept/prerequisite retrieval and graph/source memory | Report/source → related concepts/citations → prerequisite diagnostic |

Fits teammates comfortable across React, Python and storage. Main risk is duplicate policy/schema and inconsistent UI. A owns shared UI/shell, B the authoritative commit/grading/planner service, C migrations/graph/retrieval. Other slices use those boundaries. Budget about 15 hours each.

## How to choose

| Criterion | Horizontal | Vertical |
| --- | --- | --- |
| Specialist team | Better fit | Requires cross-stack work |
| Early complete demo paths | Depends on layer integration | Each person owns one |
| Central algorithm consistency | Easier for B | Shared policy boundary required |
| Main failure mode | Integration bottleneck | Duplicate logic/UI divergence |

**Selected: horizontal.** A owns layers/input; B owns layers/intelligence; C owns layers/memory. Vertical is retained only as reference. Use the H ownership column in the implementation tickets. Both descriptions refer to the same architecture, but the actual folder and responsibility split is horizontal.

## Common handoffs and deadlines

Freeze LearningInput, EvidenceEvent, ContextBundle, TopicProposal, NextActivity and LearningView in the first 20 minutes. One migration owner, one authoritative commit/policy service and one final UI owner under either option. Model proposals cannot write grades, identity or schedules.

Required accounts: OpenRouter credits and direct OpenAI billing; local Node/Python/Docker. Core runs locally with PostgreSQL, Next.js, FastAPI and Electron. No Twilio/cloud signup on the critical path.

Saturday noon: goal → persisted agent/plan → UI survives restart. Saturday 15:00: quiz → evidence → changed plan and prerequisite reason. Saturday 19:00: complete desktop loop and scheduler proof. Sunday 11:00: dedicated Apple-like polish/keyboard pass. Sunday 13:00: feature freeze. Two timed rehearsals before demo.

The reminder demo advances an explicitly labeled test clock, not real timestamps. Keep microphone/audio-text fallback and browser wrapper fallback honest. Cut calls/SMS, media generation, automatic agent splitting and broad attachments before cutting proactive plan updates, evidence freshness or review reminders.
