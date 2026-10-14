"""PostgreSQL memory: one serialized transaction per learner mutation."""
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from loke_contracts.memory import CommitGuard, ConflictError, JobLease, MemoryTurn
from loke_contracts.source import SourceDocument, SourceGraph
from sqlalchemy import (
    Integer,
    any_,
    case,
    cast,
    create_engine,
    delete,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import tables as db
from .migrations import migrate
from .retrieval import tokens
from .tiered import MemoryLimits, TieredMemory

__all__ = ["ConflictError", "Store"]


def utc(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise ValueError("Memory timestamps require timezone-aware UTC values.")
    return result.astimezone(UTC)


class Store(TieredMemory):
    def __init__(self, url: str, limits: MemoryLimits | None = None):
        self.limits = limits or MemoryLimits()
        self.engine = create_engine(url, pool_pre_ping=True)
        migrate(self.engine)

    def _lock(self, conn, learner_id):
        # The lock exists even before a learner row does and survives reset races.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": "loke:learner:" + learner_id})
        conn.execute(pg_insert(db.generations).values(learner_id=learner_id,
            generation_id=str(uuid4())).on_conflict_do_nothing())
        expiry = conn.execute(select(db.learners.c.expires_at).where(
            db.learners.c.learner_id == learner_id)).scalar_one_or_none()
        if expiry is not None and expiry <= datetime.now(UTC):
            self._delete(conn, learner_id)
        return conn.execute(select(db.generations.c.generation_id).where(
            db.generations.c.learner_id == learner_id)).scalar_one()

    def _profile(self, conn, learner_id, generation):
        row = conn.execute(select(db.learners).where(
            db.learners.c.learner_id == learner_id)).mappings().first()
        if row:
            return dict(row["data"], graph_version=row["data"].get("graph_version"), state_revision=row["revision"], generation_id=generation)
        return dict(goal="", storage_consent=False, reminders_enabled=False, study_minutes=10,
            agent_id=None, response="Set one learning goal to begin.", active_card_id=None,
            assisted_concepts=[], state_revision=0, plan_revision=0, generation_id=generation,
            graph_version=None, demo_clock_hours=0,
            expires_at=(datetime.now(UTC) + timedelta(days=7)).isoformat())

    def _records(self, conn, table, learner_id):
        return list(conn.execute(select(table.c.data).where(
            table.c.learner_id == learner_id).order_by(table.c.key)).scalars())

    def _snapshot(self, conn, learner_id, generation):
        result = self._profile(conn, learner_id, generation)
        result["events"] = list(conn.execute(select(db.events.c.data).where(
            db.events.c.learner_id == learner_id).order_by(db.events.c.sequence)).scalars())
        result["states"] = {s["concept_id"]: s for s in self._records(conn, db.states, learner_id)}
        result["sources"] = self._records(conn, db.sources, learner_id)
        plans = self._records(conn, db.plans, learner_id)
        result["plan"] = plans[0]["activities"] if plans else []
        result["notifications"] = self._records(conn, db.notifications, learner_id)
        result["review_jobs"] = list(conn.execute(select(db.jobs.c.data).where(
            db.jobs.c.learner_id == learner_id, db.jobs.c.kind == "review"
        ).order_by(db.jobs.c.due_at, db.jobs.c.key)).scalars())
        return result

    def snapshot(self, learner_id):
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            return self._snapshot(conn, learner_id, generation)

    @staticmethod
    def _guard(current, guard):
        if guard is None:
            return
        if current["generation_id"] != guard.generation_id:
            raise ConflictError("Learning history was reset. Reload before writing.")
        for key, expected in (("state_revision", guard.state_revision),
                              ("plan_revision", guard.plan_revision),
                              ("graph_version", guard.graph_version)):
            if (expected is not None or (key == "graph_version" and key in guard.model_fields_set)) and current.get(key) != expected:
                raise ConflictError(f"Memory {key} changed. Reload before writing.")

    def _outcome(self, conn, learner_id, generation, key, fingerprint):
        row = conn.execute(select(db.outcomes).where(db.outcomes.c.learner_id == learner_id,
            db.outcomes.c.generation_id == generation, db.outcomes.c.key == key,
            db.outcomes.c.expires_at > datetime.now(UTC))).mappings().first()
        if row:
            if row["fingerprint"] != fingerprint:
                raise ConflictError("This request ID was already used for different content.")
            return row["data"]
        return None

    def _replay(self, conn, learner, generation, key, fingerprint, legacy_fingerprint):
        cached = self._outcome(conn, learner, generation, key, fingerprint)
        if cached is not None or legacy_fingerprint is None:
            return cached
        request = key.split(":", 1)[1]
        return self._outcome(conn, learner, generation, "legacy:" + request, legacy_fingerprint)

    def lookup_outcome(self, learner_id, request_id, fingerprint, generation_id, operation="legacy", legacy_fingerprint=None):
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            if generation != generation_id:
                raise ConflictError("Learning history was reset.")
            return self._replay(conn, learner_id, generation, f"{operation}:{request_id}", fingerprint, legacy_fingerprint)

    def _sync(self, conn, table, learner_id, generation, records, key, extras=None):
        existing = {row["key"]: row["data"] for row in conn.execute(select(table).where(
            table.c.learner_id == learner_id)).mappings()}
        incoming = {r[key]: r for r in records}
        if len(incoming) != len(records):
            raise ValueError("Duplicate memory record IDs.")
        removed = set(existing) - set(incoming)
        if removed:
            conn.execute(delete(table).where(table.c.learner_id == learner_id,
                                            table.c.key.in_(removed)))
        for record_key, record in incoming.items():
            if existing.get(record_key) == record:
                continue
            values = dict(learner_id=learner_id, generation_id=generation, key=record_key,
                          data=record, **(extras(record) if extras else {}))
            statement = pg_insert(table).values(**values)
            conn.execute(statement.on_conflict_do_update(
                index_elements=[table.c.learner_id, table.c.key],
                set_={k: v for k, v in values.items() if k not in {"learner_id", "key"}}))

    def _persist(self, conn, learner_id, generation, before, current):
        prior = {e["id"]: e for e in before["events"]}
        incoming = {e["id"]: e for e in current["events"]}
        if len(incoming) != len(current["events"]) or any(incoming.get(k) != v for k, v in prior.items()):
            raise ValueError("Learning evidence is immutable; append a correction instead.")
        exclude = {"states", "events", "sources", "plan", "notifications", "review_jobs",
                   "state_revision", "generation_id"}
        if current["states"] != before["states"] or current["events"] != before["events"]:
            current["projection_checkpoint"] = dict(event_count=len(current["events"]),
                correction_count=conn.execute(select(func.count()).select_from(db.corrections).where(
                    db.corrections.c.learner_id == learner_id)).scalar_one(), version="projection-after-v1")
        profile = {k: v for k, v in current.items() if k not in exclude}
        statement = pg_insert(db.learners).values(learner_id=learner_id, generation_id=generation,
            revision=current["state_revision"], data=profile, expires_at=utc(current["expires_at"]))
        conn.execute(statement.on_conflict_do_update(index_elements=[db.learners.c.learner_id],
            set_=dict(data=profile, revision=current["state_revision"], expires_at=utc(current["expires_at"]))))
        sequence = conn.execute(select(func.max(db.events.c.sequence)).where(
            db.events.c.learner_id == learner_id)).scalar() or 0
        for event in current["events"]:
            if event["id"] not in prior:
                sequence += 1
                conn.execute(insert(db.events).values(learner_id=learner_id, generation_id=generation,
                    key=event["id"], data=event, sequence=sequence, observed_at=utc(event["occurred_at"])))
        if current["agent_id"]:
            statement = pg_insert(db.agents).values(learner_id=learner_id, generation_id=generation,
                key=current["agent_id"], subject="neural-signaling",
                data=dict(subject_key="neural-signaling", prompt_version="neuro-v1"))
            conn.execute(statement.on_conflict_do_nothing())
            owner = conn.execute(select(db.agents.c.key).where(db.agents.c.learner_id == learner_id,
                db.agents.c.subject == "neural-signaling")).scalar_one()
            if owner != current["agent_id"]:
                raise ConflictError("Subject agent identity cannot be replaced in this generation.")
        known_events = set(incoming)
        for state in current["states"].values():
            if not set(state["evidence_ids"]) <= known_events or any(
                    incoming[eid].get("concept_id") != state["concept_id"] for eid in state["evidence_ids"] if eid in incoming):
                raise ValueError("Concept state references unknown evidence.")
        for activity in current["plan"]:
            if not set(activity["reason_event_ids"]) <= known_events:
                raise ValueError("Plan references unknown evidence.")
        for job in current["review_jobs"] + current["notifications"]:
            if job["reason_event_id"] not in known_events:
                raise ValueError("Review references unknown evidence.")
        self._sync(conn, db.states, learner_id, generation, list(current["states"].values()), "concept_id")
        self._sync(conn, db.sources, learner_id, generation, current["sources"], "source_id",
                   lambda r: dict(terms=sorted(tokens(r["text"]))))
        self._sync(conn, db.plans, learner_id, generation,
            [dict(id="current", activities=current["plan"], revision=current["plan_revision"])], "id")
        # Maintenance jobs are outside the review snapshot and must survive learning turns.
        reviews = list(conn.execute(select(db.jobs.c.key).where(
            db.jobs.c.learner_id == learner_id, db.jobs.c.kind == "review")).scalars())
        keep = {r["id"] for r in current["review_jobs"]}
        if set(reviews) - keep:
            conn.execute(delete(db.jobs).where(db.jobs.c.learner_id == learner_id,
                                              db.jobs.c.key.in_(set(reviews) - keep)))
        for job in current["review_jobs"]:
            old = conn.execute(select(db.jobs.c.data).where(db.jobs.c.learner_id == learner_id,
                                                          db.jobs.c.key == job["id"])).scalar_one_or_none()
            if old == job:
                continue
            statement = pg_insert(db.jobs).values(learner_id=learner_id, generation_id=generation,
                key=job["id"], data=job, kind="review", status=job["status"], due_at=utc(job["due_at"]), attempts=0)
            conn.execute(statement.on_conflict_do_update(index_elements=[db.jobs.c.learner_id, db.jobs.c.key],
                set_=dict(data=job, status=job["status"], due_at=utc(job["due_at"]),
                          lease_token=None, lease_owner=None, lease_until=None)))
        self._sync(conn, db.notifications, learner_id, generation, current["notifications"], "id")

    def mutate(self, learner_id: str, request_id: str, fingerprint: str,
               expected_revision: int | None, transform: Callable[[dict[str, Any]], None],
               *, guard: CommitGuard | None = None, operation: str = "legacy", turn: MemoryTurn | None = None, legacy_fingerprint=None):
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            before = self._snapshot(conn, learner_id, generation)
            # Generation always precedes dedupe; revision validation follows a valid replay.
            if guard and guard.generation_id != generation:
                raise ConflictError("Learning history was reset.")
            key = f"{operation}:{request_id}"
            cached = self._replay(conn, learner_id, generation, key, fingerprint, legacy_fingerprint)
            if cached is not None:
                return cached
            self._guard(before, guard)
            if expected_revision is not None and before["state_revision"] != expected_revision:
                raise ConflictError("Learning state changed. Retry with a new request ID.")
            current = deepcopy(before)
            transform(current)
            if current.get("generation_id") != generation:
                raise ValueError("A transform cannot change its memory generation.")
            current["plan_revision"] = before["plan_revision"] + int(
                current["plan"] != before["plan"] or current["active_card_id"] != before["active_card_id"])
            if current != before or (turn is not None and current["storage_consent"]):
                if not current["storage_consent"]:
                    raise ValueError("Storage consent is required for a learning commit.")
                current["state_revision"] = before["state_revision"] + 1
                self._persist(conn, learner_id, generation, before, current)
                if turn is not None:
                    references = [e["id"] for e in current["events"] if e["id"] not in {p["id"] for p in before["events"]}]
                    self._record_turn(conn, learner_id, generation, f"{operation}:{request_id}", turn.scope,
                        turn.user_text, current["response"], current["agent_id"], references,
                        dict(operation=turn.operation, status="committed", matched_agent_ids=turn.matched_agent_ids))
            # Nonconsented no-ops must not create learner content or cache rows.
            if current["storage_consent"]:
                now = datetime.now(UTC)
                conn.execute(delete(db.outcomes).where(db.outcomes.c.learner_id == learner_id,
                                                       db.outcomes.c.expires_at <= now))
                statement = pg_insert(db.outcomes).values(learner_id=learner_id, generation_id=generation,
                    key=key, fingerprint=fingerprint, data=current, created_at=now,
                    expires_at=now + timedelta(hours=24))
                conn.execute(statement.on_conflict_do_update(index_elements=[db.outcomes.c.learner_id, db.outcomes.c.key],
                    set_=dict(fingerprint=fingerprint, data=current, created_at=now, expires_at=now + timedelta(hours=24))))
                expired = select(db.outcomes.c.key).where(db.outcomes.c.learner_id == learner_id).order_by(
                    db.outcomes.c.created_at.desc(), db.outcomes.c.key).offset(100)
                conn.execute(delete(db.outcomes).where(db.outcomes.c.learner_id == learner_id,
                                                       db.outcomes.c.key.in_(expired)))
            return current

    def read_events(self, learner_id, limit=100, event_ids=None):
        if not 1 <= limit <= 1000:
            raise ValueError("Event read limit must be 1 to 1000.")
        with self.engine.begin() as conn:
            self._lock(conn, learner_id)
            query = select(db.events.c.data).where(db.events.c.learner_id == learner_id)
            if event_ids is not None:
                query = query.where(db.events.c.key.in_(event_ids[:1000]))
            return list(reversed(list(conn.execute(query.order_by(db.events.c.sequence.desc()).limit(limit)).scalars())))

    def read_sources(self, learner_id, limit=100):
        if not 1 <= limit <= 1000:
            raise ValueError("Source read limit must be 1 to 1000.")
        with self.engine.begin() as conn:
            self._lock(conn, learner_id)
            return list(conn.execute(select(db.sources.c.data).where(db.sources.c.learner_id == learner_id)
                .order_by(db.sources.c.key).limit(limit)).scalars())

    def retrieve_sources(self, learner_id, query, limit=2):
        if not 1 <= limit <= 10:
            raise ValueError("Retrieval limit must be 1 to 10.")
        words = sorted(tokens(query))[:100]
        if not words:
            return []
        with self.engine.begin() as conn:
            self._lock(conn, learner_id)
            # PostgreSQL overlap plus SQL score/limit: never load the complete source collection.
            score = sum((cast(word == any_(db.sources.c.terms), Integer) for word in words), 0)
            return list(conn.execute(select(db.sources.c.data).where(db.sources.c.learner_id == learner_id,
                db.sources.c.terms.overlap(words)).order_by(score.desc(), db.sources.c.key).limit(limit)).scalars())

    def learner_ids(self):
        with self.engine.connect() as conn:
            return list(conn.execute(select(db.learners.c.learner_id).order_by(db.learners.c.learner_id)).scalars())

    def delete_learner(self, learner_id, generation_id=None):
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            if generation_id is not None and generation_id != generation:
                raise ConflictError("Learning history was already reset.")
            self._delete(conn, learner_id)

    @staticmethod
    def _delete(conn, learner_id):
        conn.execute(delete(db.learners).where(db.learners.c.learner_id == learner_id))
        conn.execute(update(db.generations).where(db.generations.c.learner_id == learner_id)
                     .values(generation_id=str(uuid4())))

    def expire(self):
        now = datetime.now(UTC)
        with self.engine.connect() as conn:
            ids = list(conn.execute(select(db.learners.c.learner_id).where(
                db.learners.c.expires_at <= now).order_by(db.learners.c.expires_at).limit(100)).scalars())
        for learner_id in ids:
            with self.engine.begin() as conn:
                self._lock(conn, learner_id)
                expiry = conn.execute(select(db.learners.c.expires_at).where(
                    db.learners.c.learner_id == learner_id)).scalar_one_or_none()
                if expiry and expiry <= now:
                    self._delete(conn, learner_id)
        with self.engine.begin() as conn:
            conn.execute(delete(db.outcomes).where(db.outcomes.c.expires_at <= now))

    def save_document_graph(self, learner_id, guard: CommitGuard, document: SourceDocument, graph: SourceGraph):
        if graph.document_id != document.id or graph.content_hash != document.content_hash:
            raise ValueError("Graph must match its original document.")
        passages = {p.id: p for p in document.passages}
        pages = {p.number: p.text for p in document.pages}
        citations = {c.id for c in graph.citations}
        concepts = {c.id for c in graph.concepts}
        for citation in graph.citations:
            passage = passages.get(citation.passage_id)
            if (citation.document_id != document.id or passage is None or citation.page != passage.page
                    or citation.section != passage.section or citation.start < passage.start
                    or citation.end > passage.end or citation.end <= citation.start
                    or pages[citation.page][citation.start:citation.end] != citation.quote):
                raise ValueError("Citation does not match the source span.")
        if not set(graph.goal_concept_ids) <= concepts:
            raise ValueError("Graph goal references unknown concepts.")
        for item in graph.concepts + graph.relations:
            if not set(item.citation_ids) <= citations:
                raise ValueError("Unknown graph citation.")
        for edge in graph.relations:
            if edge.from_id not in concepts or edge.to_id not in concepts:
                raise ValueError("Unknown relation endpoint.")
        version = document.id + ":" + graph.graph_hash
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            current = self._profile(conn, learner_id, generation)
            self._guard(current, guard)
            if not current["storage_consent"]:
                raise ValueError("Storage consent is required.")
            for key, kind, value in ((document.id, "document", document.model_dump(mode="json")),
                                     (version, "graph", graph.model_dump(mode="json"))):
                existing = conn.execute(select(db.objects.c.data).where(db.objects.c.learner_id == learner_id,
                    db.objects.c.key == key)).scalar_one_or_none()
                if existing is not None and existing != value:
                    raise ConflictError("Document/graph identity cannot overwrite different content.")
                conn.execute(pg_insert(db.objects).values(learner_id=learner_id, generation_id=generation,
                    key=key, kind=kind, document_id=document.id, data=value).on_conflict_do_nothing())
            for passage in document.passages:
                chunk = dict(source_id=document.id + ":" + passage.id, title=document.title, text=passage.text)
                conn.execute(pg_insert(db.sources).values(learner_id=learner_id, generation_id=generation,
                    key=chunk["source_id"], data=chunk, terms=sorted(tokens(passage.text))).on_conflict_do_nothing())
            if current.get("graph_version") != version:
                current["graph_version"] = version
                profile = {k: v for k, v in current.items() if k not in {"generation_id", "state_revision"}}
                conn.execute(update(db.learners).where(db.learners.c.learner_id == learner_id)
                    .values(data=profile, revision=current["state_revision"] + 1))
            return version

    def read_object(self, learner_id, key):
        with self.engine.begin() as conn:
            self._lock(conn, learner_id)
            return conn.execute(select(db.objects.c.data).where(db.objects.c.learner_id == learner_id,
                db.objects.c.key == key)).scalar_one_or_none()

    def add_correction(self, learner_id, guard, correction_id, event_id, correction):
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            current = self._profile(conn, learner_id, generation)
            self._guard(current, guard)
            if not conn.execute(select(db.events.c.key).where(db.events.c.learner_id == learner_id,
                                                               db.events.c.key == event_id)).first():
                raise ValueError("Correction references unknown evidence.")
            value = dict(event_id=event_id, correction=correction, recorded_at=datetime.now(UTC).isoformat())
            conn.execute(insert(db.corrections).values(learner_id=learner_id, generation_id=generation,
                                                      key=correction_id, event_id=event_id, data=value))
            conn.execute(update(db.learners).where(db.learners.c.learner_id == learner_id)
                         .values(revision=current["state_revision"] + 1))

    def rebuild_projection(self, learner_id, guard, reducer):
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            current = self._snapshot(conn, learner_id, generation)
            self._guard(current, guard)
            corrections = list(conn.execute(select(db.corrections.c.data).where(
                db.corrections.c.learner_id == learner_id).order_by(
                db.corrections.c.data["recorded_at"].as_string(), db.corrections.c.key)).scalars())
            # B supplies the reducer. C never infers correctness from summaries or raw text.
            projected = reducer(deepcopy(current["events"]), deepcopy(corrections))
            known = {e["id"] for e in current["events"]}
            if any(not set(s["evidence_ids"]) <= known for s in projected.values()):
                raise ValueError("Projection references unknown evidence.")
            if projected == current["states"]:
                return current
            before = deepcopy(current)
            current["states"] = projected
            current["projection_checkpoint"] = dict(event_count=len(current["events"]),
                                                      correction_count=len(corrections))
            current["state_revision"] += 1
            self._persist(conn, learner_id, generation, before, current)
            return current

    def enqueue_job(self, learner_id, generation_id, key, kind, payload, due_at=None):
        with self.engine.begin() as conn:
            generation = self._lock(conn, learner_id)
            current = self._profile(conn, learner_id, generation)
            if generation != generation_id or not current["storage_consent"]:
                raise ConflictError("Maintenance history was reset or is not consented.")
            conn.execute(pg_insert(db.jobs).values(learner_id=learner_id, generation_id=generation,
                key=key, data=payload, kind=kind, status="pending", due_at=due_at or datetime.now(UTC),
                attempts=0).on_conflict_do_nothing())

    def claim_jobs(self, owner, kinds, limit=10, lease_seconds=60):
        if "review" in kinds:
            raise ValueError("In-app reviews dispatch atomically; only maintenance jobs use leases.")
        if not 1 <= limit <= 10 or not 1 <= lease_seconds <= 900:
            raise ValueError("Job batch/lease bounds exceeded.")
        now = datetime.now(UTC)
        leases = []
        with self.engine.begin() as conn:
            conn.execute(update(db.jobs).where(db.jobs.c.kind.in_(kinds), db.jobs.c.attempts >= 3,
                or_(db.jobs.c.status == "pending", (db.jobs.c.status == "leased") &
                    (db.jobs.c.lease_until <= now))).values(status="failed", lease_token=None,
                                                          lease_owner=None, lease_until=None))
            rows = list(conn.execute(select(db.jobs).where(db.jobs.c.kind.in_(kinds), db.jobs.c.attempts < 3,
                db.jobs.c.due_at <= now, or_(db.jobs.c.status == "pending",
                    (db.jobs.c.status == "leased") & (db.jobs.c.lease_until <= now)))
                .order_by(db.jobs.c.due_at, db.jobs.c.learner_id, db.jobs.c.key)
                .limit(limit).with_for_update(skip_locked=True)).mappings())
            for row in rows:
                token, deadline = str(uuid4()), now + timedelta(seconds=lease_seconds)
                conn.execute(update(db.jobs).where(db.jobs.c.learner_id == row["learner_id"],
                    db.jobs.c.key == row["key"]).values(status="leased", lease_token=token,
                    lease_owner=owner, lease_until=deadline, attempts=row["attempts"] + 1))
                leases.append(JobLease(id=row["key"], learner_id=row["learner_id"],
                    generation_id=row["generation_id"], kind=row["kind"], token=token, owner=owner,
                    expires_at=deadline, payload=row["data"]))
        return leases

    def finish_job(self, lease, success=True):
        with self.engine.begin() as conn:
            result = conn.execute(update(db.jobs).where(db.jobs.c.learner_id == lease.learner_id,
                db.jobs.c.generation_id == lease.generation_id, db.jobs.c.key == lease.id,
                db.jobs.c.status == "leased", db.jobs.c.lease_token == lease.token,
                db.jobs.c.lease_owner == lease.owner, db.jobs.c.lease_until > datetime.now(UTC))
                .values(status="completed" if success else case((db.jobs.c.attempts >= 3, "failed"), else_="pending"), lease_token=None,
                        lease_owner=None, lease_until=None, due_at=datetime.now(UTC) + timedelta(minutes=15)))
            if result.rowcount != 1:
                raise ConflictError("Job lease is expired, replaced or reset.")
