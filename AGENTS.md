# Layer C guardrails

Follow docs/LAYER_C_PLAN.md and the four dependent PR slices. Read the current slice and its acceptance criteria before editing. Keep the offline learning loop runnable.

- PostgreSQL is the only runtime and integration-test database. Never silently substitute SQLite.
- C owns storage, retrieval, compaction and partition maintenance. B owns assessment and teaching policy. Only app.py imports concrete memory into intelligence.
- Every write and retrieval is learner/generation scoped. UI project/folder/concept tags are ranking hints, never authorization or proof of knowledge.
- Raw evidence and operational histories are canonical. Summaries are versioned derived context. Splits reference records; they do not copy evidence or execute autonomous child agents.
- No provider calls during tests or background maintenance. Keep extractive summarization as the default.
- Do not add services, embeddings, agent frameworks, new UI flows or connectors to complete this plan.
- Each PR contains one named plan slice, relevant behavioral tests and explicit limitations. Run PostgreSQL concurrency tests with independent connections. Never report skipped database checks as passed.
- Before committing, inspect the diff, run applicable tests and ruff, and exclude secrets, databases and generated scratch assets. Generate public TypeScript from Python contracts.
- Do not merge, deploy or modify external accounts. The current instruction authorizes commits, pushes and draft PRs for these slices.
- Use no em or en dashes in user-facing responses.
