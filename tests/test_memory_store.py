from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from loke_contracts.memory import CommitGuard, ConflictError
from loke_contracts.models import GoalInput
from loke_intelligence.coordinator import Coordinator
from loke_memory import tables as db
from loke_memory.store import Store
from sqlalchemy import select, update


def goal(store, learner="one", request="goal"):
    return Coordinator(store).goal(learner, GoalInput(request_id=request,
        goal="Understand neural signaling", storage_consent=True))


def test_independent_stores_serialize_initial_agents(pg_url):
    stores = [Store(pg_url), Store(pg_url)]
    with ThreadPoolExecutor(2) as pool:
        views = list(pool.map(lambda s: goal(s), stores))
    assert views[0].agent_id == views[1].agent_id
    assert views[0].state_revision == views[1].state_revision == 1
    assert len(stores[0].learner_ids()) == 1
    for store in stores:
        store.engine.dispose()


def test_generation_guard_survives_reset_and_reconsent(pg_url):
    store = Store(pg_url)
    goal(store)
    before = store.snapshot("one")
    guard = CommitGuard(generation_id=before["generation_id"], state_revision=1)
    store.delete_learner("one")
    goal(store)
    with pytest.raises(ConflictError, match="reset"):
        store.mutate("one", "stale", "stale", 1, lambda s: s.update(response="bad"), guard=guard)
    assert store.snapshot("one")["response"] != "bad"
    assert store.snapshot("one")["generation_id"] != before["generation_id"]


def test_rollback_noop_and_immutable_events(pg_url):
    store = Store(pg_url)
    goal(store)
    initial = store.snapshot("one")
    result = store.mutate("one", "noop", "noop", 1, lambda s: None)
    assert result == initial
    def broken(s):
        s["response"] = "partial"
        raise RuntimeError("failure")
    with pytest.raises(RuntimeError):
        store.mutate("one", "broken", "broken", 1, broken)
    assert store.snapshot("one") == initial
    event = dict(id="e1", concept_id=None, kind="study_report", text="note",
                 occurred_at=datetime.now(UTC).isoformat(), assessment="not_assessed",
                 assistance="none", source="text")
    saved = store.mutate("one", "event", "event", 1, lambda s: s["events"].append(event))
    with pytest.raises(ValueError, match="immutable"):
        store.mutate("one", "edit", "edit", 2, lambda s: s["events"][0].update(text="edited"))
    assert store.snapshot("one") == saved
    assert store.lookup_outcome("one", "event", "event", saved["generation_id"]) == saved
    with pytest.raises(ConflictError):
        store.lookup_outcome("one", "event", "different", saved["generation_id"])


def test_cache_is_bounded_and_deleted_with_content(pg_url):
    store = Store(pg_url)
    goal(store)
    for index in range(105):
        store.mutate("one", str(index), str(index), None, lambda s: None)
    with store.engine.connect() as conn:
        assert len(list(conn.execute(select(db.outcomes.c.key)))) == 100
    generation = store.snapshot("one")["generation_id"]
    assert store.lookup_outcome("one", "0", "0", generation) is None
    store.delete_learner("one")
    with store.engine.connect() as conn:
        for table in (db.learners, db.agents, db.events, db.states, db.sources, db.plans,
                      db.jobs, db.notifications, db.outcomes, db.corrections, db.objects):
            assert conn.execute(select(table)).first() is None
        assert conn.execute(select(db.generations)).first() is not None


def test_projection_reducer_and_corrections_preserve_evidence(pg_url):
    store = Store(pg_url)
    goal(store)
    event = dict(id="e1", concept_id="ionic_gradients", text="observed",
                 occurred_at=datetime.now(UTC).isoformat())
    snapshot = store.mutate("one", "event", "event", 1, lambda s: s["events"].append(event))
    guard = CommitGuard(generation_id=snapshot["generation_id"], state_revision=2)
    store.add_correction("one", guard, "c1", "e1", {"assessment": "ungraded"})
    guard = guard.model_copy(update={"state_revision": 3})
    def reducer(events, corrections):
        assert events == [event]
        assert corrections[0]["event_id"] == "e1"
        return {"ionic_gradients": dict(concept_id="ionic_gradients", status="attempted", evidence_ids=["e1"])}
    rebuilt = store.rebuild_projection("one", guard, reducer)
    assert rebuilt["events"] == [event]
    assert rebuilt["state_revision"] == 4
    store.delete_learner("one")


def test_sql_retrieval_is_scoped_and_deterministic(pg_url):
    store = Store(pg_url)
    goal(store)
    goal(store, "two")
    sources = [dict(source_id="b", title="B", text="sodium potassium"),
               dict(source_id="a", title="A", text="sodium potassium"),
               dict(source_id="c", title="C", text="calcium")]
    store.mutate("one", "sources", "sources", 1, lambda s: s.update(sources=sources))
    assert [s["source_id"] for s in store.retrieve_sources("one", "sodium")] == ["a", "b"]
    assert store.retrieve_sources("two", "sodium") == []
    assert store.retrieve_sources("one", "unmatched") == []


def test_job_claim_recovery_and_stale_completion(pg_url):
    store, other = Store(pg_url), Store(pg_url)
    goal(store)
    generation = store.snapshot("one")["generation_id"]
    store.enqueue_job("one", generation, "m1", "maintenance", {"node": "root"})
    first = store.claim_jobs("worker-a", ["maintenance"])[0]
    assert other.claim_jobs("worker-b", ["maintenance"]) == []
    with store.engine.begin() as conn:
        conn.execute(update(db.jobs).values(lease_until=datetime.now(UTC) - timedelta(seconds=1)))
    second = other.claim_jobs("worker-b", ["maintenance"])[0]
    with pytest.raises(ConflictError):
        store.finish_job(first)
    other.finish_job(second)
    assert store.claim_jobs("worker-a", ["maintenance"]) == []
    other.engine.dispose()


def test_graph_roundtrip_exact_citations_and_version_guard(pg_url):
    import asyncio

    from loke_intelligence.source_discovery import discover_source_graph
    from loke_intelligence.source_documents import ingest_source
    store = Store(pg_url)
    goal(store)
    document = ingest_source(b"## Alpha\nAlpha: first concept.\n## Beta\nBeta: second concept.\nAlpha is a prerequisite for Beta.", "source.md")
    graph = asyncio.run(discover_source_graph(document, "Learn Beta"))
    current = store.snapshot("one")
    guard = CommitGuard(generation_id=current["generation_id"], state_revision=1, graph_version=None)
    version = store.save_document_graph("one", guard, document, graph)
    assert store.read_object("one", version) == graph.model_dump(mode="json")
    assert store.read_object("two", version) is None
    assert store.snapshot("one")["state_revision"] == 2
    with pytest.raises(ConflictError):
        store.mutate("one", "old-graph", "old-graph", None, lambda s: s.update(response="stale"), guard=guard)
    broken = graph.model_copy(deep=True)
    broken.citations[0].quote = "fabricated"
    with pytest.raises(ValueError, match="span"):
        store.save_document_graph("one", CommitGuard(generation_id=current["generation_id"]), document, broken)
    store.delete_learner("one")
    assert store.read_object("one", document.id) is None
