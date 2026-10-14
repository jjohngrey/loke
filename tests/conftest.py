"""Every database test gets a real PostgreSQL schema; never fall back to SQLite."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def pg_url():
    url = os.environ.get("LOKE_TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set LOKE_TEST_DATABASE_URL to an isolated PostgreSQL test database.")
    engine = create_engine(url)
    name = "test_" + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{name}"'))
    scoped = url + ("&" if "?" in url else "?") + "options=-csearch_path%3D" + name
    try:
        yield scoped
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        engine.dispose()
