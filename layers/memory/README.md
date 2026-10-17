# C: PostgreSQL memory

Own persistence, scoped retrieval, transactional invariants, graph/source records, compaction,
durable maintenance jobs and cleanup. Teaching/grading policy remains in intelligence.

PostgreSQL is required. Startup rejects SQLite URLs and leaves existing SQLite files untouched.
Start the database with `docker compose up -d`; set DATABASE_URL from `.env.example`.
Versioned migrations run under a PostgreSQL advisory lock. Back up before upgrading.

The Store serializes learner writes across independent connections, validates generation/state/
plan/graph guards, appends immutable evidence and writes targeted projection/plan/source/job updates
atomically. Consent is required for content writes. Reset and expiry cascade through all retained
learner content and rotate a content-free generation marker. Successful request replay lasts
24 hours with at most 100 stored outcomes per learner generation; evicted IDs have no guarantee.

All chats use the same Coordinator. ChatScope supplies a stable chat ID, optional project ID,
folder path, concept tags and node tags. Conversation histories and summaries stay per chat;
agent search crosses that learner's chats and categories. Content/tag matches qualify a candidate;
project/folder overlap improves ranking but cannot qualify an unrelated agent or grant access.
The current UI is a separate scaffold: clients must send ChatScope to use distinct chat identities.
No project/folder editor or external account integration is added by C.

Conversation messages and committed action logs are recorded atomically with a goal/input/answer.
Provider attempts/results are separately logged as operational actions, never learning evidence.
Raw logs survive summarization and restart until the learner explicitly deletes their history. Profiles have no automatic expiry.
Earlier complete conversations cannot be reconstructed because the scaffold never stored them.

Every 15 minutes, durable leased maintenance compacts older interactions and splits oversized log
partitions. Defaults: summarize at 100 unsummarized messages while retaining the newest 40 for
context selection; split above 200 records or 12,000 estimated tokens. Offline summaries preserve
exact dated excerpts, original references and literal goal/preference statements. They do not
claim complete semantic task understanding. Higher tiers cite lower summaries. Originals remain
retrievable by ID. Summaries and log text are untrusted context; canonical evidence/state prevails.
No paid background summarization or autonomous child execution loops run.

Category roots keep stable agent IDs. Their B+ tree partitions ordered append sequences, not
semantic topic names. Internal nodes route by disjoint ranges; leaves hold canonical record
references. Semantic tags/search select relevant leaves independently of chronology. Maximum
fanout eight, depth six and ten splits per maintenance batch. At saturation, indexed overflow
is retained and MemoryContext reports maintenance_saturated. Child node IDs are persistent
memory routing identities, not independently running model processes.

Memory context is bounded to 3,000 estimated tokens using the versioned UTF-8 byte estimator.
B also bounds the full serialized retrieval context to 3,000 estimated tokens, excluding the current
user input and system prompt. Truncation and candidate-scan limits are explicit. The compatibility
snapshot API still reads full retained learning-event/source collections; pagination of that
legacy UI/policy path is future work. Event/source read APIs and agent search are SQL bounded.

Documents, passages, exact citations and immutable source-graph versions round-trip through
shared DTOs. Source text is indexed for on-demand retrieval. Equal labels across sources are not
merged. Reviewed catalog prerequisites/related edges are separate from discovered graphs.
Projection replay uses B's explicit projection-after records. Legacy events without those inputs
cannot be exactly replayed; legacy timestamps are marked unverified rather than reinterpreted.
Corrections are append-only, with explicit replacement projections required for changed grades.
Correction callers must supply B's resulting plan/review decisions; C never invents those decisions.

In-app review dispatch is one learner transaction, with consent, due time, latest evidence and
24-hour notification cap checked inside it. It needs no external-delivery lease. Maintenance uses
SKIP LOCKED claims and lease tokens, with three attempts maximum and crash recovery. Active quiz
sessions, snooze and notification actions still require the separate B/A lifecycle contracts.

See `docs/LAYER_C_PLAN.md` and `docs/MEMORY_OPERATIONS.md`. Verification requires
LOKE_TEST_DATABASE_URL pointing at an isolated PostgreSQL database; tests create random schemas.
