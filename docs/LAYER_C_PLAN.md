# Layer C implementation plan

Status: implemented across four stacked PRs. See the memory README and MEMORY_OPERATIONS.md for shipped behavior and limits. Repository: /Users/johngrey/loke. Scope: memory storage, retrieval, graph persistence, atomic commits, durable jobs and cleanup. Implementation and verification are recorded in the final handoff.

## Baseline and boundaries

The current Store bootstraps eight tables with SQLAlchemy create_all. Most records are JSON; events append, but states, sources, plans and jobs are replaced per mutation. Successful request outcomes are full snapshots stored indefinitely in jobs. The Python lock protects one Store instance, not separate processes. Retrieval loads every source into Python. Expiry reads and deletes in separate transactions. Events can be changed in the callback snapshot without the database recording those changes. The public MemoryPort is a dictionary/callback boundary.

B has independently implemented source-document extraction and source-scoped graph discovery. These records are not persisted or wired to HTTP. Its source models currently live in intelligence. Public generation, expected-plan-version, quiz-session and notification-action fields are proposals, not shipped contracts.

C will own storage and transactional invariants. B retains grading, projection semantics, plan selection, graph discovery and notification eligibility. A retains UI and upload flows. Shared-contract changes will be narrow, generated from Python, with existing HTTP payloads preserved during the transition. Only app.py may import concrete memory implementations into intelligence.

## 1. Define the memory boundary

Add storage-neutral models and port operations for commit preconditions/results, bounded reads, request outcomes, graph/document persistence, reset and job claims. Move or re-export source persistence DTOs through shared contracts without changing discovery behavior. Define shared conflict types and retain the existing mutate API as a compatibility adapter while callers migrate.

Commit preconditions include learner, generation, state revision, relevant plan revision and active graph identity/version. Model work runs outside transactions; persistence validates these captured versions again at commit. Snapshot reads include a stable generation and graph version. Accepting this plan authorizes this narrow contract slice, not the proposed quiz/notification HTTP expansion.

Acceptance: existing fixtures and API behavior remain valid; policy/coordinator do not import SQL or concrete storage; generated schemas/types match the Python contracts.

## 2. Versioned schema and safe upgrades

Replace unconditional schema bootstrap with ordered, recorded SQLAlchemy migrations. Support PostgreSQL only. Upgrade existing PostgreSQL scaffold databases. Existing SQLite files remain untouched; transferring their content requires a separately reviewed import. Reject a database schema newer than the application. Migration application must be serialized and transactional where the database supports it; PostgreSQL DDL and backfill execute in one locked transaction.

Normalize ownership, generation, timestamps, event ordering, concept/graph identity, job status/deadlines and request keys into queryable columns. Keep JSON for bounded domain payloads. Separate request outcomes, review jobs and notifications. Add foreign keys, learner/generation-scoped uniqueness, a unique learner-generation-subject agent key, deterministic indexes and explicit graph edge types. Require PostgreSQL foreign-key enforcement and reject SQLite URLs at startup.

Provide an upgrade preflight and backup procedure. If existing data cannot satisfy a constraint, report offending record IDs and stop rather than dropping or inventing learner history. Preserve existing event, source, agent and plan IDs and revisions. Treat legacy shifted evidence timestamps as legacy provenance; do not guess their original wall times.

Acceptance: populated legacy database upgrades without lost records; repeated startup is idempotent; failed migration does not leave a silently usable partial schema; fresh and upgraded databases expose the same behavior.

## 3. Atomic commits, retry outcomes and reset safety

Use database transaction serialization for writes across Store instances. PostgreSQL uses transaction-scoped learner advisory locks plus row locks and safe initialization for absent learners. Retain optimistic revision guards and translate expected concurrency/uniqueness failures into shared conflicts.

Append new immutable events and reject edits/removals of existing evidence through ordinary commits. Persist projections, plan, sources, agent identity and review changes in the same transaction using targeted writes. Detect actual changes so no-op commits do not advance state revision; plan revision follows B's explicit plan/activity change decision.

Scope dedupe by learner, generation, operation and request ID, with a canonical fingerprint. An identical retry within the retention window returns the exact committed outcome; changed payload conflicts. Add preflight lookup so B can avoid a provider call on completed retries, with authoritative dedupe still at commit. Cache defaults: 24-hour expiry and 100 successful outcomes per learner generation. Once evicted, an old request ID has no replay guarantee; document this explicitly. Concurrent in-flight provider-call suppression is B orchestration work, not a storage claim.

Delete and expiry erase learner content and cached outcomes atomically, then rotate a minimal content-free generation marker. Retain that marker for the lifetime of the local installation to prevent stale work from becoming valid after re-consent. Marker contains identity key and generation metadata only, no goals, sources, evidence or provider output. Expiry rechecks eligibility in the deleting transaction. Evidence observation and retention use UTC wall time; demo time only affects review eligibility.

Acceptance: concurrent initial goals create one agent; failures roll back all writes; stale generation/revision/graph work writes nothing; delete then re-consent rejects old work even when revision numbers repeat; no-op reads/dispatches do not bump revisions; cleanup removes all learner content.

## 4. Replayable projections

Store stable event ordering and projection version/checkpoint metadata. Implement replay orchestration in C using a deterministic reducer supplied by B. The store must not invent grading or review policy. Rebuild concept state from immutable evidence without duplicating events, changing agent identity, redispatching notifications or silently rewriting historical plans.

Support explicit correction records referencing the original event, keeping the original immutable. Automatic replay is limited to projection fields that the accepted event schema can reconstruct. If assistance/deadline decisions require missing historical inputs, preserve those inputs going forward and identify legacy limitations rather than asserting exact replay.

Acceptance: incremental projection and replay agree for supported report, incorrect, ungraded and assisted/unassisted answer sequences; corrections are traceable; invalid correction references fail atomically.

## 5. Persist documents, graphs and bounded retrieval

Persist extracted documents/pages/passages, exact citations and immutable graph versions scoped to learner generation and document content hash. Preserve graph_hash separately from content_hash. Store node/edge IDs, relation kind, origin, basis, usable/held status, coverage and warnings. Never merge equal labels across documents or promote discovered nodes into the reviewed catalog. Seed reviewed prerequisite and related edges explicitly.

Replacing the active graph creates a new version and invalidates commits based on the previous active version. Preserve older versions while retained evidence references them. Learner reset/expiry removes all versions and source content. Individual source deletion semantics remain a later public API decision.

Provide SQL-filtered, indexed reads for recent events, referenced evidence, citations and sources. For source search, use an indexed token lookup backed by PostgreSQL GIN indexes, preserving current token-overlap ranking, top-two defaults and stable ID tie breaks. Bound candidate and result counts and disclose truncation. Avoid full learner-history loading for model context; retain compatibility snapshot reads for current UI callers until B/A adopt pagination. No vector database or embeddings.

Acceptance: source/document/graph round trips preserve exact quote offsets and provenance; cross-learner/cross-generation lookups fail; graph replacement does not alter historical evidence; bounded retrieval returns deterministic matches or an empty result.

## 6. OpenPoke-inspired tiered memory and category-agent trees

Adopt the three-tier architecture from the OpenPoke description supplied by the user: recent interactions at full fidelity, compressed older conversation context, and on-demand retrieval from durable agent logs and external records. This is an architectural reference, not a claim that Loke already implements OpenPoke internals. Unlike the original weekend scope, automatic memory splitting is now explicitly included at the user's request.

### Conversation memory

Persist an ordered, consent-scoped interaction ledger containing learner messages, committed assistant responses and relevant action references. Store message ID, generation, observation timestamp, role, category/agent reference and evidence/source references. Existing evidence events remain separate; an assistant explanation or conversation summary cannot become assessment evidence. Begin complete logging from implementation onward; do not invent missing historical assistant messages.

Use a configurable 100-unsummarized-message trigger. Keep the newest 40 messages at full fidelity in the assembled context. Summarize a closed older range into a structured record with covered sequence bounds, timestamp range, goals/preferences, open/completed activities, unresolved questions, corrections and canonical message/event/source references. Preserve exact dates and distinguish a request, an attempted action and a successful committed result. Never compress away a correction or turn a reported study session into a correct answer.

Cascade summaries when a tier exceeds its configured budget, retaining references to child summaries and the original records. Defaults: at most eight summaries per tier before compaction and a 3,000-token total assembled-memory budget, reserving space for the current request, policy and retrieved sources. Recent messages are trimmed to fit when individually large; explicit record retrieval can recover the omitted text. Raw ledgers remain available until their consent/retention deadline, even when omitted from model context. Compression reduces prompt size, not data-retention obligations.

Summaries are versioned derived caches with coverage checkpoints, source fingerprints, generator version and status. A failed summary keeps the prior valid context; a stale generation or changed source range prevents publication. B owns semantic summarization through an injected interface; C owns scheduling, persistence, validation of references, compare-and-swap publication and invalidation. Offline mode uses deterministic extractive summaries. Model summarization is optional, bounded and disabled by default; any future live background summarization must follow configured provider consent and spending limits.

### Durable category-agent memory

Each learning category has a stable root agent with its own append-only operational ledger. Capture action ID, parent action, agent/category, input references, tool name/version, start/end UTC timestamps, success/failure/cancellation, bounded result payload or durable artifact reference and evidence/source links. Never retain secrets, raw audio or unrestricted provider debug payloads. A log records what happened; only B's accepted assessment path writes learning evidence.

Maintain complete retained operational history across restart and repartitioning. Roots and children retrieve canonical records rather than copying divergent history. Existing learner-subject agent identity stays stable. Children have stable identities, a parent, routing boundaries and summaries; they are memory-backed category agents, not automatically running model processes. B can execute a selected child through its existing orchestration boundary. Tree maintenance itself never invokes arbitrary tools or spawns autonomous execution loops.

### B-tree structure and background splitting

A classical B-tree partitions an ordered keyspace. Semantic categories can overlap, so a tree based solely on model-created topic names cannot provide B-tree lookup guarantees. Implement a B-tree-like memory hierarchy with exact ordered partition invariants, and add semantic tags as a separate retrieval index.

Within each category root, index operational records by `(append_sequence, record_id)`, retaining observed_at as temporal provenance. Internal nodes store disjoint child key ranges, counts, token estimates and versioned summaries. Leaves own record references. This makes chronology retrieval precise while labels such as resting potential or transmitter release help search select relevant ranges. Semantic search can select multiple leaves; uncertain queries use the parent and bounded index search rather than guessing a single child.

Default split policy: a leaf becomes eligible above 200 records or 12,000 estimated tokens. Split at a deterministic median key into two balanced children with nonempty ranges. Use maximum fanout eight for internal nodes; split overflowing internal nodes and propagate upward while preserving the category root ID through an extra internal level. Keep all leaves at equal depth, except the root-only tree. A single oversized record remains one referenced artifact with a bounded preview and is never repeatedly split. Token counting has an explicit versioned estimator, distinct from exact provider token usage.

C runs an application-owned maintenance job every 15 minutes, configurable, with startup catch-up. This is the requested cron-style process implemented through durable jobs, not a system crontab or Codex chat automation. Checkpoint scans and process at most ten leaves per run. Jobs are deduplicated by generation, root, node and tree version and use the lease mechanism below. Request handling may enqueue maintenance when a threshold is crossed; it does not perform recursive splitting inline.

Build the new node/range assignments outside the publish transaction from a fixed sequence watermark. Atomically publish the new tree version only if generation, node version and watermark still match. Concurrent appended records remain visible in an indexed unsplit tail and are attached on the next maintenance pass; a parent read includes that tail. On failure or crash, the old version remains readable and the lease can recover. Splitting changes memory organization only, not learner evidence, agent identity, state revision or plan revision.

Use a hard maximum depth of six. When that limit is reached, keep overflow in indexed paginated leaves and expose maintenance saturation rather than dropping records or creating unbounded agents. Reset/expiry removes summaries, operational logs, tree nodes, artifact references, indexes and maintenance jobs in the same generation-scoped cleanup. Deletion can prune empty nodes and collapse single-child internal nodes; balancing after bulk deletion must finish before publishing a new tree version. Do not compact unrelated category roots into one learner-memory blob.

### On-demand external memory

For this implementation, external memory means the learner's consented uploaded documents, persisted citations/graphs and explicitly stored tool results. Retrieve relevant records only when needed, with source IDs, observation/source timestamps, scope and freshness. The provider interface allows future email/calendar integrations, but this plan does not connect Gmail or ingest the user's inbox. External text is untrusted source data and never an instruction to the agent. A stale or unavailable source produces an explicit limitation rather than a fabricated recollection.

### Schema and port additions

Add interaction_messages, agent_log_entries, memory_summaries, memory_nodes and memory_assignments, plus durable summarization/split maintenance job types. Scope all rows to learner/generation and agent/category. Enforce unique sequence/action keys, parent ownership, exclusive leaf assignment per tree version and source-range references. Store tree revision separately from learning state/plan revision.

Expose append/read interaction, append/read agent log, bounded context assembly, explicit original-record lookup, tree traversal, enqueue/claim maintenance and guarded summary/tree publication through shared ports. Model input receives a typed context bundle with recent messages, summaries, selected log excerpts and sources, all with provenance and truncation metadata. Model output cannot write directly to these tables.

Acceptance: 100-message threshold produces a valid summary while keeping the recent tail; cascading summaries preserve temporal facts and original-record lookup; category logs survive restart; splitting preserves every retained record exactly once in the published tree; range ordering, balanced depth and fanout hold; cross-category queries can search several leaves; oversized records and depth caps terminate safely; concurrent append, competing workers, stale generation, crash recovery and deletion do not lose or resurrect content. Test deterministic offline summarization and injected provider fakes, with no paid background calls.

## 7. Durable job claims and dispatch integration

Add pending/leased/completed/cancelled jobs with due_at, lease owner/token, lease expiry, attempts and stable dispatch keys. Claim due jobs atomically and in deterministic order. PostgreSQL uses locked candidate selection with SKIP LOCKED. Completion verifies lease ownership; expired leases can be reclaimed; stale workers cannot complete a reclaimed job. Cancellation on newer evidence/reset and unique notification dispatch occur transactionally.

Wire the current scheduler through the shared port. B's existing consent, latest-evidence and daily-cap checks must run again inside the dispatch transaction. Store claims and emits one durable in-app notification per dispatch key. Cleanup gets its own hourly cadence with bounded batches. Restart catches overdue jobs without requiring model calls.

Do not claim active-quiz suppression or snooze support until those B/A lifecycle contracts exist. Leases support multiple backend workers, but the full learner-facing multi-worker claim requires tests on PostgreSQL.

Acceptance: competing workers claim once; crash and lease expiry recover; stale lease completion fails; notification insert is deduplicated; disabled reminders/stale jobs/reset block dispatch; empty ticks do not change learner revisions.

## 8. Verification and handoff

Add meaningful store/migration tests for legacy upgrade, rollback, immutable evidence, generation reset races, cache eviction/retry, concurrent agent creation, projection replay, source/graph isolation, bounded queries, lease recovery, notification uniqueness, conversation compaction and memory-tree invariants. Use separate Store instances and independent connections for concurrency tests rather than one Python lock. Run the store contract suite against isolated PostgreSQL schemas; missing PostgreSQL is a blocking prerequisite for claiming database verification.

Run existing learning-loop, policy, source-discovery and fixture tests, contract generation, frontend typecheck, ruff and frontend build. Verify the real offline loop: goal, wrong answer, prerequisite, source persistence, restart, due reminder, reset and stale-write rejection. No paid provider calls are needed. If PostgreSQL or native desktop verification is unavailable, report it as unverified.

Update the memory README and ownership/handoff docs to distinguish shipped features from remaining proposals. Deliver migration/backup instructions, exact changed contracts, tests and limitations. No commit, push or deployment without a separate instruction.

## Delivery order and exclusions

Implement boundary and migration foundation first, then atomic/reset/cache behavior, replay, graph/retrieval, durable jobs, tiered conversation/category memory, tree maintenance and final integration. Each slice preserves a runnable offline baseline. This is a substantial backend implementation, not just a schema-file edit.

Excluded: teaching-policy redesign, new quiz/notification UI and routes, PDF extraction changes, model-generated assessments, live API testing, autonomous child execution loops, Gmail/calendar ingestion, cross-document ontology merging, embeddings, Redis/Neo4j, SMS and public hosting.

## Shared orchestrator and user organization

All chats invoke the same stateless orchestrator implementation. It performs explicit learner-scoped agent-memory search before choosing relevant category roots/leaves. Chats carry stable chat IDs and optional project ID, folder path and concept tags. These are retrieval hints and provenance, not authorization boundaries and not instructions to force an agent. Access always follows server-selected learner/generation and stored consent.

Projects, folders and subfolders are user-visible organization. Internal memory splitting remains application-owned; no one-to-one folder-to-agent requirement. A chat may tag several graph concepts or memory nodes. Store the association separately from semantic edges; a UI tag never creates a prerequisite, changes evidence or merges concepts across documents. Retrieval uses lexical content overlap, matching concept/node tags, organization overlap and recency, with deterministic tie breaks and bounded result counts. Content matches may retrieve agents from other chats/folders of the same learner. Organization hints alone do not manufacture a semantic match; an empty search yields an explicit no-match path.

An agent-log row records chat provenance; conversation summarization is scoped to chat so separate conversations are not flattened together. The orchestrator searches across the learner's consented category-agent histories and external source records. Selected memory appears as cited, bounded context, not an instruction or authority to grade. Child agents are persisted routing identities, not new autonomous loops.

## Atomic PR sequence and guardrails

1. C1, foundation: approved plan, repository guardrails, shared memory/source contracts, versioned PostgreSQL schema/migration foundation. Commit: define memory contracts and migration boundary.
2. C2, transactions: replace bootstrap Store, enforce PostgreSQL, atomic generation/version/dedupe/reset, targeted persistence, projection checkpoints/corrections and bounded source/graph reads. Commit: enforce durable memory invariants.
3. C3, hierarchy: per-chat conversations, durable category logs, structured cascading summaries, bounded B-tree-like partitioning, organization hints and agent search. Commit: add tiered category memory.
4. C4, integration: shared orchestrator retrieval/context, durable scheduler/maintenance leases, offline recording, migration/backup instructions, PostgreSQL CI and end-to-end verification. Commit: integrate and verify memory lifecycle.

PRs are stacked and reviewed/merged in order, each targeting its predecessor. Do not merge automatically. Each contains its own relevant tests; final integration runs the whole suite. Preserve teaching policy and current UI behavior. Avoid new services, generic agent frameworks, embeddings and paid background calls. If a slice cannot meet its acceptance tests, keep it draft and identify the exact failure. No hidden catch-and-ignore for migration errors, stale writes or lost records. Limit tree fanout/depth, context, cache, maintenance batches and retry counts through validated configuration.

Implementation simplification: offline summaries are extractive excerpts with dates and original references. They do not claim semantic preservation of every preference/task; a future B summarizer may supply richer structured fields. B+ tree splits use bounded SQL updates inside the existing learner transaction, avoiding a second snapshot-publication protocol. Child memory nodes are persistent routing identities, not provider agents.

Verified final slice: PostgreSQL 17, 151 offline tests, generated-contract/typecheck checks, ruff and production frontend build passed. In-app review dispatch uses a single guarded transaction; leases are reserved for maintenance jobs because no external delivery happens. Expired content is removed at the access boundary as well as hourly cleanup. UI clients can adopt optional chat/version envelopes without a UI redesign in C.
