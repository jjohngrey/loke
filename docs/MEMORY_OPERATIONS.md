# Layer C operation and integration

## Database setup

Use PostgreSQL 17. Docker setup from the repository root:

```sh
docker compose up -d postgres
cp .env.example .env
uv sync --locked
npm install
npm run dev
```

For an existing `.env`, change DATABASE_URL without replacing provider keys or other preferences.
The application requires PostgreSQL and fails early when the URL selects SQLite. SQLite files
are preserved; there is no automatic SQLite-to-PostgreSQL transfer in this change.

Before first startup against existing PostgreSQL data, stop other app versions and back up:

```sh
pg_dump --format=custom --file=work/loke-before-memory.dump "$DATABASE_URL_PSQL"
```

DATABASE_URL_PSQL is a task-specific PostgreSQL CLI URL, using `postgresql://` rather than
SQLAlchemy's `postgresql+psycopg://`. Do not print credentials in logs. Test restoration into a
separate database with `pg_restore`. Restore a full pre-upgrade backup with the previous app
version to roll back; there is no lossy automated downgrade.

Migrations acquire one transaction advisory lock, create versioned tables, backfill existing
PostgreSQL scaffold records and remove old learner-content tables only after successful copying.
They preserve IDs, revisions and content. Orphan records or incompatible constraints abort the
whole transaction and identify bounded record IDs. Migration does not reinterpret legacy event
timestamps or invent old conversational messages. A newer schema version is rejected.

Schema versions: 1, normalized memory foundation; 2, reviewed catalog and correction deletion
constraints; 3, conversation/log/summaries and tree references. SQLite is never a runtime fallback.

## Chat and orchestrator boundary

Every chat goes through the same Coordinator instance/implementation. A learner is selected by
server session context. Supply organization information as hints in a learning request:

```json
{
  "request_id": "unique-retry-id",
  "generation_id": "generation-from-current-view",
  "expected_state_revision": 4,
  "text": "How does sodium entry relate to depolarization?",
  "scope": {
    "chat_id": "chat-17",
    "project_id": "neuroscience",
    "folder_path": ["cellular", "membranes"],
    "concept_tags": ["action_potential_phases"],
    "node_tags": []
  }
}
```

Goal and answer accept the same optional generation/version/scope envelope. Answer also accepts
expected_plan_revision. Existing clients can omit the envelope for compatibility; the server
captures and guards the base generation before work. To reject delayed browser writes after a
reset, clients must send generation_id. DELETE /api/learner accepts a generation_id query guard.
Reminder/clock writes accept request_id and optional generation/version guards. Clock advance and
its first eligible review notification commit together. A successful identical retry returns its
committed result; a reused request ID with a different payload conflicts. Operation scope is
learner/generation/operation/request ID, so clients should issue globally unique retry IDs per
operation, including across chats.

Agent retrieval searches indexed content, concept/node tags and organization overlap, then uses
recency and stable IDs to break ties. At most 50 candidate rows contribute to five or fewer matches;
the default is three. A folder alone cannot produce a semantic match. Scope hints never restrict
authorized recall to one folder or permit recall from another learner. There is no new global
singleton with mixed learner state, and no separate orchestrator per folder.

SourceGraph and SourceDocument are shared contracts. `save_document_graph` verifies document,
content hash, exact quote spans, concept/relation endpoints and citation references, then persists
immutable graph versions and source passages. `read_object` retrieves retained originals. Tags
are metadata, never semantic prerequisite edges. Document/category execution and UI selection
remain owned by B/A; the current grading/HTTP loop still uses the reviewed neuroscience catalog.

## Maintenance and retention

The application scheduler is the cron-style runner. No system crontab or chat automation is needed.
It catches up at startup, checks reviews every 30 seconds, runs cleanup hourly and enqueues memory
maintenance every 15 minutes. Multiple workers use SKIP LOCKED jobs and lease tokens. Failed work
retries at most three times, then remains visibly failed in the jobs table; no silent infinite loop.

Configure summary trigger/tail, leaf count/token limit and context limit through MEMORY_* settings
in `.env.example`; values are validated. Hard caps: fanout eight, depth six, ten leaves per job and
3,000 estimated context tokens. The estimator is UTF-8 bytes divided by three, rounded up; it is
not a promise about exact model-provider token counts. Tree reads expose a tree_version guard and sequence cursor for safe bounded navigation.
Source/record IDs allow on-demand lookup
when a context excerpt is truncated.

Memory partitions use ordered sequence ranges in a balanced B+ tree. Splits reference existing
records and do not copy log/evidence bodies. The root ID stays stable, every log has one leaf
assignment, and internal splits preserve equal leaf depth. At the depth cap, overflow stays in
indexed leaves and maintenance_saturated is exposed. Model processes are not spawned by splitting.

The existing seven-day learner expiry applies to every content tier: raw messages/logs, summaries,
source documents/graphs, projections, outcomes, nodes/assignments and jobs. Compression does not
extend retention. Reset/expiry erases these together and retains only a learner key/generation
marker for the installation lifetime. Marker rows contain no learner content. Old generations and
leases cannot write into the new history. Provider-side retention is unaffected by local deletion.

## Tests and scope

```sh
export DATABASE_URL='postgresql+psycopg://loke:loke@127.0.0.1:5432/loke_test'
export LOKE_TEST_DATABASE_URL="$DATABASE_URL"
npm run check
uv run ruff check .
npm run build
```

Use an isolated database: tests create/drop random schemas, and module-level app initialization
creates the application's own empty schema tables there. They never substitute SQLite. Concurrent
checks use independent Store instances and real PostgreSQL connections. CI repeats the offline
suite, typecheck, generation drift check and build. No provider credentials are needed.

Known limits: summaries are extractive, not LLM semantic summaries; no email/calendar integration;
no UI chat/folder CRUD or quiz/notification lifecycle redesign; no live-provider evaluation;
compatibility snapshot reads and stored outcomes still contain full retained learning snapshots;
no cross-document ontology merging; no automatic counterfactual teaching-policy replay for legacy
or corrected grades. These are explicit integration boundaries, not shipped claims.

Completed request retries skip model calls. Concurrent first attempts across workers may still
invoke a provider more than once before one guarded learning commit wins; in-flight provider
call coalescing remains B orchestration work. Settings, clock and review commits also append
operational logs, and original-record lookup can resolve their notification/evidence references.
