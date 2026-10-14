"""Transactional, serialized PostgreSQL migration with lossless legacy backfill."""
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import MetaData, Table, insert, inspect, select, text

from . import tables as db
from .retrieval import tokens

VERSION = 1


def migrate(engine):
    if engine.dialect.name != "postgresql":
        raise ValueError("Loke memory requires PostgreSQL; SQLite files are not modified.")
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(1819241317)"))
        db.versions.create(conn, checkfirst=True)
        current = conn.execute(select(db.versions.c.version)).scalar_one_or_none()
        if current is not None and current > VERSION:
            raise ValueError("Database schema is newer than this application.")
        if current == VERSION:
            return
        db.metadata.create_all(conn)
        if "learners" in inspect(conn).get_table_names():
            _legacy(conn)
        conn.execute(insert(db.versions).values(version=VERSION))


def _legacy(conn):
    legacy = MetaData()
    names = ("learners", "agents", "learning_events", "concept_state", "sources", "plans", "jobs")
    old = {name: Table(name, legacy, autoload_with=conn) for name in names}
    for row in conn.execute(select(old["learners"])).mappings():
        learner, profile, generation = row["id"], row["data"], str(uuid4())
        conn.execute(insert(db.generations).values(learner_id=learner, generation_id=generation))
        conn.execute(insert(db.learners).values(learner_id=learner, generation_id=generation,
            revision=row["revision"], data=profile,
            expires_at=datetime.fromisoformat(profile["expires_at"])))
        mapping = {"agents": db.agents, "learning_events": db.events, "concept_state": db.states,
                   "sources": db.sources, "plans": db.plans, "jobs": db.jobs}
        for name, target in mapping.items():
            records = list(conn.execute(select(old[name]).where(old[name].c.learner_id == learner)).mappings())
            if name == "learning_events":
                records.sort(key=lambda r: (r["data"]["occurred_at"], r["id"]))
            for sequence, record in enumerate(records, 1):
                target = mapping[name]
                data, extra = record["data"], {}
                key = data.get("id", record["id"].removeprefix(f"{learner}:"))
                if name == "agents":
                    key = record["id"]
                    extra["subject"] = data["subject_key"]
                elif name == "learning_events":
                    extra = dict(sequence=sequence, observed_at=datetime.fromisoformat(data["occurred_at"]))
                elif name == "concept_state":
                    key = data["concept_id"]
                elif name == "sources":
                    key, extra = data["source_id"], dict(terms=sorted(tokens(data["text"])))
                elif name == "jobs":
                    if data["kind"] == "request":
                        # Retain committed legacy outcomes for one bounded retry window.
                        target = db.outcomes
                        key = "legacy:" + record["id"].removeprefix(f"request:{learner}:")
                        now = datetime.now(UTC)
                        from datetime import timedelta
                        extra = dict(fingerprint=data["fingerprint"], created_at=now,
                                     expires_at=now + timedelta(hours=24))
                        data = data["outcome"] | {"generation_id": generation}
                    elif data["kind"] == "notification":
                        target = db.notifications
                    else:
                        extra = dict(kind="review", status=data["status"], attempts=0,
                                     due_at=datetime.fromisoformat(data["due_at"]))
                conn.execute(insert(target).values(learner_id=learner, generation_id=generation,
                                                   key=key, data=data, **extra))
    # The successful backfill removes legacy learner-content tables, avoiding undeleted copies.
    # Keep the global reviewed concepts table for backward compatibility.
    for name in reversed(names):
        old[name].drop(conn)
