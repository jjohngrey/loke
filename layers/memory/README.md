# C: backend memory

Own schema, scoped persistence/retrieval, migrations, durable jobs and cleanup. Keep teaching/grading policy out of this layer.

`schema.py` defines eight bootstrap tables. `store.py` separates profiles, evidence, concept-state projections, source chunks, plans and jobs.
SQLite starts immediately; Docker Compose plus DATABASE_URL enables PostgreSQL through the same SQLAlchemy boundary.
`shared/contracts/loke_contracts/catalog.py` is the reviewed seed catalog owned by C.

Next work: versioned migrations instead of create_all, relational/FK constraints, job leases and multi-worker claims, projection replay/corrections, SQL-backed retrieval, bounded request-result cache and PostgreSQL integration checks.
The scaffold is explicitly single-worker. Do not claim production-grade job execution or graph/RAG behavior.
