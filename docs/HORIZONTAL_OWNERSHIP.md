# Selected ownership: horizontal

| Owner | Folder | Boundary |
| --- | --- | --- |
| A | layers/input | React/Next.js, Electron, forms, microphone and attachments; emit input and render committed results |
| B | layers/intelligence | Coordinator/topic logic, deterministic grades/plans, model adapters and review policy |
| C | layers/memory | Persistence, graph/source retrieval, atomic commits, job storage and deletion |

Shared contracts live in `shared/contracts`. B owns their Python shape; A consumes generated TypeScript; C implements MemoryPort. C owns the seed catalog. Agree schema changes before regenerating types.

Only the composition root `loke_intelligence/app.py` imports the memory implementation. The intelligence policy and coordinator use shared contracts. Input calls the intelligence HTTP API through an authenticated Next.js proxy.

## Implemented starter loop

Goal + consent → persistent subject agent → three-step plan → quiz answer → event/state/plan/review commit → unchecked prerequisite → scheduled in-app notification. Text/Markdown notes become reported activity and separate source chunks. PostgreSQL records survive process restart. Layer C now supplies generation guards, tiered chat/category memory, bounded retrieval and durable maintenance; see MEMORY_OPERATIONS.md.

This is a scaffold with a small working deterministic loop, not the complete MVP. Live OpenRouter and OpenAI audio adapters are included but paid calls were not exercised. PostgreSQL 17 memory behavior is verified; run Docker Compose or a local PostgreSQL server. Native Electron startup is separately verified where the host supports it.

## Integration checkpoints

1. A renders the generated LearningView and fixture states.
2. B produces a typed input/proposal and one deterministic next activity.
3. C persists the same evidence/projection and preserves agent identity after restart.
4. Whole-flow test: real UI submit → backend commit → changed plan → due reminder.

B coordinates full-loop integration. C reserves three hours for A/B integration as specified in the plan. A performs the final common visual/keyboard pass.

## Known extension points

- Active quiz begin/complete/cancel and scheduler suppression.
- Snooze/read/dismiss reminders and retention-friendly notification cleanup.
- Plan completion and explicit source citations in live model replies.
- Further B/A adoption of typed lifecycle contracts and graph/category execution; C now provides migrations, scoped foreign keys, maintenance leases and explicit projection replay.
- Better prerequisite coverage and per-session assisted-answer boundaries.
- Audio duration/type validation and record/unmount cancellation.
- Packaged desktop distribution, optional OS notification and secondary channels.
