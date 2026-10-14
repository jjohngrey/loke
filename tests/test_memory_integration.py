import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from loke_contracts.memory import ChatScope, CommitGuard, ConflictError
from loke_contracts.models import AnswerInput, ClockAdvance, LearningInput, TopicProposal
from loke_intelligence import policy
from loke_intelligence.coordinator import Coordinator
from loke_intelligence.scheduler import ReviewScheduler
from loke_memory import tables as base
from loke_memory import tiered_tables as db
from loke_memory.store import Store
from loke_memory.tiered import MemoryLimits
from sqlalchemy import select, update

from .test_memory_store import goal


def test_shared_orchestrator_retrieves_across_chats_and_retry_avoids_provider(pg_url, monkeypatch):
    store = Store(pg_url)
    goal(store)
    offline = Coordinator(store)
    asyncio.run(offline.input("one", LearningInput(request_id="a", text="Sodium channels open.",
        scope=ChatScope(chat_id="a", project_id="biology", folder_path=["neurons"]))))
    captured = []
    async def provider(text, context):
        captured.append(context)
        assert context.memory.matches
        assert any(e.chat_id == "a" for e in context.memory.logs)
        assert all(e.chat_id == "b" for e in context.memory.recent)
        return TopicProposal(concept_id="action_potential_phases", explanation="Sodium entry supports depolarization.")
    monkeypatch.setattr("loke_intelligence.coordinator.propose", provider)
    live = Coordinator(store, "live")
    current = store.snapshot("one")
    payload = LearningInput(request_id="b", text="How do sodium channels work?",
        scope=ChatScope(chat_id="b", project_id="other"), generation_id=current["generation_id"],
        expected_state_revision=current["state_revision"])
    first = asyncio.run(live.input("one", payload))
    replay = asyncio.run(live.input("one", payload))
    assert first == replay
    assert len(captured) == 1
    with store.engine.connect() as conn:
        assert len(list(conn.execute(select(db.messages.c.key).where(db.messages.c.chat_id == "b")))) == 2
        rows = list(conn.execute(select(db.logs.c.data)))
        statuses = [r[0]["action"]["status"] for r in rows]
        assert "started" in statuses and "succeeded" in statuses


def test_transcript_failure_rolls_back_learning_commit(pg_url, monkeypatch):
    store = Store(pg_url)
    goal(store)
    before = store.snapshot("one")
    with store.engine.connect() as conn:
        old_messages = len(list(conn.execute(select(db.messages))))
    original = store._record_turn
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("transcript failure")
    monkeypatch.setattr(store, "_record_turn", fail)
    with pytest.raises(RuntimeError):
        asyncio.run(Coordinator(store).input("one", LearningInput(request_id="fail", text="Sodium")))
    assert store.snapshot("one") == before
    with store.engine.connect() as conn:
        assert len(list(conn.execute(select(db.messages)))) == old_messages
    assert store.lookup_outcome("one", "fail", "any", before["generation_id"], operation="input") is None


def test_demo_clock_does_not_shift_observation_and_clock_replay_is_exact(pg_url, monkeypatch):
    monkeypatch.setenv("DEMO_CLOCK_ENABLED", "true")
    store = Store(pg_url)
    goal(store)
    service = Coordinator(store)
    clock = ClockAdvance(request_id="clock", hours=24, generation_id=store.snapshot("one")["generation_id"],
                         expected_state_revision=1)
    first = service.advance_clock("one", 24, clock)
    assert service.advance_clock("one", 24, clock) == first
    before = datetime.now(UTC)
    view = asyncio.run(service.input("one", LearningInput(request_id="note", text="Sodium")))
    assert before <= view.events[-1].occurred_at <= datetime.now(UTC)
    assert view.demo_clock_hours == 24


def test_concurrent_reviews_dispatch_once_and_empty_ticks_do_not_mutate(pg_url):
    store, other = Store(pg_url), Store(pg_url)
    goal(store)
    Coordinator(store).answer("one", AnswerInput(request_id="answer", card_id="ap-depolarization", answer="A"))
    store.mutate("one", "shift", "shift", None, lambda s: s.update(demo_clock_hours=24))
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda s: Coordinator(s).tick("one"), [store, other]))
    snapshot = store.snapshot("one")
    assert len(snapshot["notifications"]) == 1
    Coordinator(other).tick("one")
    assert store.snapshot("one") == snapshot
    other.engine.dispose()


def test_projection_replay_matches_incremental_answer_state(pg_url):
    store = Store(pg_url)
    goal(store)
    service = Coordinator(store)
    service.answer("one", AnswerInput(request_id="a", card_id="ap-depolarization", answer="A"))
    service.answer("one", AnswerInput(request_id="b", card_id="resting-permeability", answer="K+"))
    service.answer("one", AnswerInput(request_id="c", card_id="ap-repolarization", answer="A"))
    before = store.snapshot("one")
    rebuilt = store.rebuild_projection("one", CommitGuard(generation_id=before["generation_id"],
        state_revision=before["state_revision"]), policy.replay_projection)
    assert rebuilt["states"] == before["states"]
    assert rebuilt["state_revision"] == before["state_revision"]
    assert rebuilt["events"] == before["events"]


def test_maintenance_catches_up_and_does_not_change_learning_revisions(pg_url):
    store = Store(pg_url)
    goal(store)
    store.limits = MemoryLimits(summary_trigger=10, recent_messages=4, leaf_records=2)
    service = Coordinator(store)
    for index in range(5):
        asyncio.run(service.input("one", LearningInput(request_id=str(index), text="Sodium")))
    revision = store.snapshot("one")["state_revision"]
    scheduler = ReviewScheduler(service, store)
    scheduler.cycle()
    with store.engine.connect() as conn:
        assert conn.execute(select(db.summaries)).first()
        assert any(row[0] == "completed" for row in conn.execute(select(base.jobs.c.status)))
    assert store.snapshot("one")["state_revision"] == revision
    asyncio.run(scheduler.stop())


def test_stale_client_generation_rejected_before_provider(pg_url, monkeypatch):
    store = Store(pg_url)
    goal(store)
    generation = store.snapshot("one")["generation_id"]
    store.delete_learner("one")
    goal(store)
    async def forbidden(*args):
        raise AssertionError("Stale client must not invoke a paid provider")
    monkeypatch.setattr("loke_intelligence.coordinator.propose", forbidden)
    with pytest.raises(ConflictError, match="reset"):
        asyncio.run(Coordinator(store, "live").input("one", LearningInput(request_id="stale",
            text="Sodium", generation_id=generation)))


def test_retry_budget_stops_maintenance_failures(pg_url):
    store = Store(pg_url)
    goal(store)
    generation = store.snapshot("one")["generation_id"]
    store.enqueue_job("one", generation, "bad", "memory", {})
    for index in range(3):
        lease = store.claim_jobs("worker", ["memory"])[0]
        store.finish_job(lease, success=False)
        with store.engine.begin() as conn:
            conn.execute(update(base.jobs).where(base.jobs.c.key == "bad").values(
                due_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert store.claim_jobs("worker", ["memory"]) == []
    with store.engine.connect() as conn:
        assert conn.execute(select(base.jobs.c.status).where(base.jobs.c.key == "bad")).scalar_one() == "failed"


def test_whole_model_context_is_bounded_without_mutating_records(pg_url, monkeypatch):
    from loke_intelligence.memory_context import cost
    store = Store(pg_url)
    goal(store)
    offline = Coordinator(store)
    text = "Sodium channels " * 800
    for index in range(15):
        asyncio.run(offline.input("one", LearningInput(request_id=f"large-{index}", text=text)))
    captured = []
    async def provider(text, context):
        captured.append(context)
        assert cost(context) <= 3000
        assert context.context_truncated
        return TopicProposal(concept_id=None, explanation="This is a bounded source excerpt.")
    monkeypatch.setattr("loke_intelligence.coordinator.propose", provider)
    asyncio.run(Coordinator(store, "live").input("one", LearningInput(request_id="live", text="Sodium")))
    assert captured
    assert store.read_events("one", event_ids=[store.read_events("one")[0]["id"]])[0]["text"] == text


def test_expired_content_is_unavailable_before_hourly_cleanup(pg_url):
    store = Store(pg_url)
    goal(store)
    current = store.snapshot("one")
    asyncio.run(Coordinator(store).input("one", LearningInput(request_id="source", text="Sodium", mode="attachment")))
    with store.engine.begin() as conn:
        conn.execute(update(base.learners).where(base.learners.c.learner_id == "one").values(
            expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert store.retrieve_sources("one", "Sodium") == []
    assert store.read_events("one") == []
    assert store.snapshot("one")["generation_id"] != current["generation_id"]
    with store.engine.connect() as conn:
        for table in (db.messages, db.logs, db.nodes, base.outcomes, base.events):
            assert conn.execute(select(table)).first() is None
