from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any

from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.engine import Connection

from . import schema as db
from .seed import CONCEPTS


class ConflictError(ValueError):
    pass


class Store:
    """One transaction per learning turn; events, states and plans are separate records."""

    def __init__(self, url: str):
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        options = (
            {"connect_args": {"check_same_thread": False, "timeout": 10}}
            if url.startswith("sqlite")
            else {}
        )
        self._lock = RLock()
        self.engine = create_engine(url, **options)
        db.metadata.create_all(self.engine)
        with self._lock, self.engine.begin() as conn:
            for concept in CONCEPTS:
                if (
                    conn.execute(
                        select(db.concepts.c.id).where(db.concepts.c.id == concept["id"])
                    ).first()
                    is None
                ):
                    conn.execute(insert(db.concepts).values(id=concept["id"], data=concept))

    def _profile(self, conn: Connection, learner_id: str) -> dict[str, Any]:
        row = (
            conn.execute(select(db.learners).where(db.learners.c.id == learner_id))
            .mappings()
            .first()
        )
        if row:
            return dict(row["data"], state_revision=row["revision"])
        return dict(
            goal="",
            storage_consent=False,
            reminders_enabled=False,
            study_minutes=10,
            agent_id=None,
            response="Set one learning goal to begin.",
            active_card_id=None,
            assisted_concepts=[],
            state_revision=0,
            plan_revision=0,
            demo_clock_hours=0,
            expires_at=(datetime.now(UTC) + timedelta(days=7)).isoformat(),
        )

    def _records(self, conn: Connection, table, learner_id: str) -> list[dict[str, Any]]:
        return list(
            conn.execute(select(table.c.data).where(table.c.learner_id == learner_id)).scalars()
        )

    def _snapshot(self, conn: Connection, learner_id: str) -> dict[str, Any]:
        profile = self._profile(conn, learner_id)
        profile["states"] = {s["concept_id"]: s for s in self._records(conn, db.states, learner_id)}
        profile["events"] = sorted(
            self._records(conn, db.events, learner_id), key=lambda e: e["occurred_at"]
        )
        profile["sources"] = self._records(conn, db.sources, learner_id)
        stored_plans = self._records(conn, db.plans, learner_id)
        profile["plan"] = stored_plans[0]["activities"] if stored_plans else []
        profile["notifications"] = [
            j for j in self._records(conn, db.jobs, learner_id) if j.get("kind") == "notification"
        ]
        profile["review_jobs"] = [
            j for j in self._records(conn, db.jobs, learner_id) if j.get("kind") == "review"
        ]
        return profile

    def snapshot(self, learner_id: str) -> dict[str, Any]:
        with self._lock, self.engine.connect() as conn:
            return self._snapshot(conn, learner_id)

    def _replace(
        self, conn: Connection, table, learner_id: str, records: list[dict[str, Any]], key: str
    ):
        conn.execute(delete(table).where(table.c.learner_id == learner_id))
        for record in records:
            conn.execute(
                insert(table).values(
                    id=f"{learner_id}:{record[key]}", learner_id=learner_id, data=record
                )
            )

    def mutate(
        self,
        learner_id: str,
        request_id: str,
        fingerprint: str,
        expected_revision: int | None,
        transform: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        request_key = f"request:{learner_id}:{request_id}"
        with self._lock, self.engine.begin() as conn:
            cached = conn.execute(
                select(db.jobs.c.data).where(db.jobs.c.id == request_key)
            ).scalar_one_or_none()
            if cached:
                if cached["fingerprint"] != fingerprint:
                    raise ConflictError("This request ID was already used for different content.")
                return cached["outcome"]
            # Lock existing profile for PostgreSQL. SQLite is supported with one app worker.
            conn.execute(
                select(db.learners.c.id).where(db.learners.c.id == learner_id).with_for_update()
            ).first()
            current = self._snapshot(conn, learner_id)
            revision = current["state_revision"]
            if expected_revision is not None and expected_revision != revision:
                raise ConflictError("Learning state changed. Retry with a new request ID.")
            prior_event_ids = {e["id"] for e in current["events"]}
            transform(current)
            current["state_revision"] = revision + 1
            profile = {
                k: v
                for k, v in current.items()
                if k
                not in {
                    "states",
                    "events",
                    "sources",
                    "plan",
                    "notifications",
                    "review_jobs",
                    "state_revision",
                }
            }
            exists = conn.execute(
                select(db.learners.c.id).where(db.learners.c.id == learner_id)
            ).first()
            if exists:
                result = conn.execute(
                    update(db.learners)
                    .where(db.learners.c.id == learner_id, db.learners.c.revision == revision)
                    .values(data=profile, revision=revision + 1)
                )
                if result.rowcount != 1:
                    raise ConflictError("Concurrent learning update. Retry.")
            else:
                conn.execute(
                    insert(db.learners).values(id=learner_id, data=profile, revision=revision + 1)
                )
            for event in current["events"]:
                if event["id"] not in prior_event_ids:
                    conn.execute(
                        insert(db.events).values(
                            id=f"{learner_id}:{event['id']}", learner_id=learner_id, data=event
                        )
                    )
            if (
                current["agent_id"]
                and not conn.execute(
                    select(db.agents.c.id).where(db.agents.c.id == current["agent_id"])
                ).first()
            ):
                conn.execute(
                    insert(db.agents).values(
                        id=current["agent_id"],
                        learner_id=learner_id,
                        data={"subject_key": "neural-signaling", "prompt_version": "neuro-v1"},
                    )
                )
            self._replace(
                conn, db.states, learner_id, list(current["states"].values()), "concept_id"
            )
            self._replace(conn, db.sources, learner_id, current["sources"], "source_id")
            self._replace(
                conn,
                db.plans,
                learner_id,
                [
                    {
                        "id": "current",
                        "activities": current["plan"],
                        "revision": current["plan_revision"],
                    }
                ],
                "id",
            )
            conn.execute(
                delete(db.jobs).where(
                    db.jobs.c.learner_id == learner_id, ~db.jobs.c.id.like("request:%")
                )
            )
            for job in current["review_jobs"] + current["notifications"]:
                conn.execute(
                    insert(db.jobs).values(
                        id=f"{learner_id}:{job['id']}", learner_id=learner_id, data=job
                    )
                )
            conn.execute(
                insert(db.jobs).values(
                    id=request_key,
                    learner_id=learner_id,
                    data={"kind": "request", "fingerprint": fingerprint, "outcome": current},
                )
            )
            return current

    def read_events(self, learner_id: str) -> list[dict[str, Any]]:
        return self.snapshot(learner_id)["events"]

    def read_sources(self, learner_id: str) -> list[dict[str, Any]]:
        return self.snapshot(learner_id)["sources"]

    def retrieve_sources(self, learner_id: str, query: str) -> list[dict[str, Any]]:
        from .retrieval import retrieve_chunks

        return retrieve_chunks(query, self.read_sources(learner_id))

    def learner_ids(self) -> list[str]:
        with self._lock, self.engine.connect() as conn:
            return list(conn.execute(select(db.learners.c.id)).scalars())

    def delete_learner(self, learner_id: str):
        with self._lock, self.engine.begin() as conn:
            for table in [db.events, db.states, db.sources, db.plans, db.jobs, db.agents]:
                conn.execute(delete(table).where(table.c.learner_id == learner_id))
            conn.execute(delete(db.learners).where(db.learners.c.id == learner_id))

    def expire(self):
        for learner_id in self.learner_ids():
            if datetime.fromisoformat(self.snapshot(learner_id)["expires_at"]) <= datetime.now(UTC):
                self.delete_learner(learner_id)
