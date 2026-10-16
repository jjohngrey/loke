from datetime import UTC, datetime, timedelta

import pytest
from loke_memory import schema as legacy
from loke_memory import tables as db
from loke_memory.migrations import VERSION, migrate
from sqlalchemy import create_engine, insert, inspect, select


def test_fresh_migration_is_idempotent(pg_url):
    engine = create_engine(pg_url)
    migrate(engine)
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(select(db.versions.c.version)).scalar_one() == VERSION
    engine.dispose()


def test_legacy_upgrade_preserves_records_and_removes_old_content(pg_url):
    engine = create_engine(pg_url)
    legacy.metadata.create_all(engine)
    with engine.begin() as conn:
        profile = dict(expires_at=(datetime.now(UTC) + timedelta(days=7)).isoformat())
        conn.execute(insert(legacy.learners).values(id="one", revision=3, data=profile))
        event = dict(id="e1", occurred_at=datetime.now(UTC).isoformat(), text="original")
        conn.execute(insert(legacy.events).values(id="one:e1", learner_id="one", data=event))
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(select(db.events.c.data)).scalar_one() == dict(event, timestamp_provenance="legacy_unverified")
        assert conn.execute(select(db.learners.c.revision)).scalar_one() == 3
        assert "learning_events" not in inspect(conn).get_table_names()
    engine.dispose()


def test_rejects_sqlite():
    engine = create_engine("sqlite://")
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        migrate(engine)


def test_orphan_legacy_records_abort_without_losing_original_data(pg_url):
    engine = create_engine(pg_url)
    legacy.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(legacy.events).values(id="orphan", learner_id="missing", data={}))
    with pytest.raises(ValueError, match="unowned record IDs"):
        migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(select(legacy.events.c.id)).scalar_one() == "orphan"
        assert "memory_learners" not in inspect(conn).get_table_names()
    engine.dispose()


def test_legacy_request_outcome_replays_without_duplicate_goal(pg_url):
    import hashlib
    import json

    from loke_contracts.models import GoalInput
    from loke_intelligence.coordinator import Coordinator, legacy_fingerprint
    from loke_memory.store import Store

    from .fakes import FakeMemory
    engine = create_engine(pg_url)
    legacy.metadata.create_all(engine)
    payload = GoalInput(request_id="goal", goal="Understand neural signaling", storage_consent=True)
    old_payload = dict(request_id="goal", goal=payload.goal, storage_consent=True,
                       reminders_enabled=True, study_minutes=10)
    old_fingerprint = hashlib.sha256(json.dumps(old_payload, separators=(",", ":")).encode()).hexdigest()
    assert legacy_fingerprint(payload) == old_fingerprint
    snapshot = FakeMemory().snapshot("one")
    snapshot.update(goal=payload.goal, storage_consent=True, agent_id="legacy-agent",
                    state_revision=1, response="Legacy committed response")
    snapshot.pop("generation_id")
    profile = {k: v for k, v in snapshot.items() if k not in
               {"events", "states", "sources", "plan", "notifications", "review_jobs", "state_revision"}}
    with engine.begin() as conn:
        conn.execute(insert(legacy.learners).values(id="one", revision=1, data=profile))
        conn.execute(insert(legacy.agents).values(id="legacy-agent", learner_id="one",
            data={"subject_key": "neural-signaling", "prompt_version": "neuro-v1"}))
        conn.execute(insert(legacy.jobs).values(id="request:one:goal", learner_id="one",
            data=dict(kind="request", fingerprint=old_fingerprint, outcome=snapshot)))
    store = Store(pg_url)
    replay = Coordinator(store).goal("one", payload)
    assert replay.state_revision == 1
    assert replay.response == "Legacy committed response"
    assert replay.agent_id == "legacy-agent"
    assert store.snapshot("one")["state_revision"] == 1
    from loke_contracts.memory import ChatScope, ConflictError
    changed = payload.model_copy(update={"scope": ChatScope(chat_id="different-chat")})
    with pytest.raises(ConflictError, match="different content"):
        Coordinator(store).goal("one", changed)
    store.engine.dispose()
    engine.dispose()


def test_newer_database_schema_is_rejected(pg_url):
    engine = create_engine(pg_url)
    db.versions.create(engine)
    with engine.begin() as conn:
        conn.execute(insert(db.versions).values(version=999))
    with pytest.raises(ValueError, match="newer"):
        migrate(engine)
    engine.dispose()


def test_upgrade_removes_existing_deadline_without_deleting_history(pg_url):
    from loke_memory.store import Store

    from .test_memory_store import goal

    store = Store(pg_url)
    goal(store)
    before = store.snapshot("one")
    with store.engine.begin() as conn:
        conn.execute(db.learners.update().values(
            expires_at=datetime.now(UTC) - timedelta(days=1),
            data=dict(before, expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat())))
        conn.execute(db.versions.update().values(version=3))
        conn.exec_driver_sql("ALTER TABLE memory_learners ALTER COLUMN expires_at SET NOT NULL")
    reopened = Store(pg_url)
    reopened.expire()
    after = reopened.snapshot("one")
    assert after["expires_at"] is None
    assert after["generation_id"] == before["generation_id"]
    assert after["goal"] == before["goal"]
    with reopened.engine.connect() as conn:
        assert conn.execute(select(db.learners.c.expires_at)).scalar_one() is None
    reopened.delete_learner("one")
    assert reopened.snapshot("one")["generation_id"] != before["generation_id"]
    store.engine.dispose()
    reopened.engine.dispose()
