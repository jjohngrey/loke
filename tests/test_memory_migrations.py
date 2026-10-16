from datetime import UTC, datetime, timedelta

import pytest
from loke_memory import schema as legacy
from loke_memory import tables as db
from loke_memory.migrations import migrate
from sqlalchemy import create_engine, insert, inspect, select


def test_fresh_migration_is_idempotent(pg_url):
    engine = create_engine(pg_url)
    migrate(engine)
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(select(db.versions.c.version)).scalar_one() == 1
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
        assert conn.execute(select(db.events.c.data)).scalar_one() == event
        assert conn.execute(select(db.learners.c.revision)).scalar_one() == 3
        assert "learning_events" not in inspect(conn).get_table_names()
    engine.dispose()


def test_rejects_sqlite():
    engine = create_engine("sqlite://")
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        migrate(engine)
