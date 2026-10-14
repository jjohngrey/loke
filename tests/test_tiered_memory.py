from concurrent.futures import ThreadPoolExecutor

import pytest
from loke_contracts.memory import ChatScope, ConflictError
from loke_memory import tiered_tables as db
from loke_memory.store import Store
from loke_memory.tiered import MemoryLimits, estimate
from sqlalchemy import select

from .test_memory_store import goal


def setup(store, category="neural-signaling"):
    goal(store)
    generation = store.snapshot("one")["generation_id"]
    root = store.ensure_category_agent("one", generation, category)
    return generation, root


def turn(store, generation, root, index, scope=None, text="sodium channel"):
    return store.record_turn("one", generation, str(index), scope or ChatScope(chat_id="chat-a"),
        text, "Saved as reported activity", root, action={"operation": "report", "status": "committed"})


def test_conversations_are_separate_and_agents_cross_folder_boundaries(pg_url):
    store = Store(pg_url)
    generation, root = setup(store)
    scope = ChatScope(chat_id="chat-a", project_id="biology", folder_path=["cells", "ions"], concept_tags=["sodium"])
    first = turn(store, generation, root, 1, scope)
    second = turn(store, generation, root, 2, ChatScope(chat_id="chat-b", project_id="chemistry"), "potassium")
    context = store.memory_context("one", generation, "sodium", ChatScope(chat_id="chat-b", project_id="chemistry"))
    assert context.matches[0].root_id == root
    assert "content_match" in context.matches[0].reasons
    assert all(e.chat_id == "chat-b" for e in context.recent)
    assert first["log"] in context.matches[0].record_ids
    assert store.search_agents("one", generation, "unrelated", scope.model_copy(update={"concept_tags": []})) == []
    assert store.original_record("two", store.snapshot("two")["generation_id"], first["log"]) is None
    assert store.original_record("one", generation, second["log"])["scope"]["chat_id"] == "chat-b"


def test_summary_threshold_cascade_and_original_records(pg_url):
    store = Store(pg_url)
    generation, root = setup(store)
    store.limits = MemoryLimits(summary_trigger=10, recent_messages=4, summaries_per_tier=2)
    references = []
    for index in range(14):
        references.append(turn(store, generation, root, index))
        store.maintain_memory("one", generation)
    with store.engine.connect() as conn:
        rows = list(conn.execute(select(db.summaries)).mappings())
        assert any(r["tier"] == 1 for r in rows)
        assert len(list(conn.execute(select(db.messages).where(db.messages.c.chat_id == "chat-a")))) == 28
    summary = next(r for r in rows if r["tier"] == 0)
    assert summary["data"]["generator"] == "extractive-v1"
    assert summary["data"]["entries"][0]["observed_at"] in summary["data"]["text"]
    original = store.original_record("one", generation, references[0]["user"])
    assert original["text"] == "sodium channel"
    context = store.memory_context("one", generation, "sodium", ChatScope(chat_id="chat-a"))
    assert context.summaries
    assert len(context.recent) <= 4
    assert estimate(context.model_dump_json()) <= store.limits.context_tokens


def test_default_hundred_message_trigger_preserves_recent_tail(pg_url):
    store = Store(pg_url)
    generation, root = setup(store)
    for index in range(49):
        turn(store, generation, root, index)
    store.maintain_memory("one", generation)
    with store.engine.connect() as conn:
        assert conn.execute(select(db.summaries)).first() is None
    turn(store, generation, root, 49)
    store.maintain_memory("one", generation)
    with store.engine.connect() as conn:
        summary = conn.execute(select(db.summaries)).mappings().one()
        assert summary["end_sequence"] == 60
    context = store.memory_context("one", generation, "", ChatScope(chat_id="chat-a"))
    assert 0 < len(context.recent) <= 40
    assert context.summaries
    assert context.truncated


def tree_invariants(store, count, fanout, max_depth):
    with store.engine.connect() as conn:
        nodes = {r["key"]: dict(r["data"], parent=r["parent_id"]) for r in conn.execute(select(db.nodes)).mappings()}
        assignments = list(conn.execute(select(db.assignments)).mappings())
        logs = list(conn.execute(select(db.logs.c.key)).scalars())
    assert len(assignments) == len(logs) == count
    assert len({r["key"] for r in assignments}) == count
    depths = set()
    for key, node in nodes.items():
        assert len(node["children"]) <= fanout
        if not node["children"]:
            assigned = [r for r in assignments if r["node_id"] == key]
            assert len(assigned) == node["count"]
            depth, cursor = 0, node
            while cursor["parent"]:
                cursor = nodes[cursor["parent"]]
                depth += 1
            depths.add(depth)
            assert depth <= max_depth
        else:
            children = [nodes[child] for child in node["children"]]
            assert node["count"] == sum(c["count"] for c in children)
            assert node["tokens"] == sum(c["tokens"] for c in children)
            for left, right in zip(children, children[1:]):
                assert left["high"] < right["low"]
    assert len(depths) == 1


def test_tree_balances_and_retains_every_log_on_restart(pg_url):
    store = Store(pg_url)
    generation, root = setup(store)
    store.limits = MemoryLimits(leaf_records=3, fanout=3, max_depth=3)
    for index in range(80):
        turn(store, generation, root, index)
        store.maintain_memory("one", generation)
    tree_invariants(store, 81, 3, 3)
    restarted = Store(pg_url)
    assert restarted.search_agents("one", generation, "sodium", ChatScope())
    assert store.snapshot("one")["state_revision"] == 1
    restarted.engine.dispose()


def test_oversized_record_and_competing_maintenance_are_safe(pg_url):
    store, other = Store(pg_url), Store(pg_url)
    generation, root = setup(store)
    turn(store, generation, root, 0, text="x" * 15000)
    assert store.maintain_memory("one", generation)["splits"] == 0
    turn(store, generation, root, 1, text="sodium")
    store.limits = other.limits = MemoryLimits(leaf_records=2, leaf_tokens=100)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda s: s.maintain_memory("one", generation), [store, other]))
    tree_invariants(store, 3, 8, 6)
    store.delete_learner("one")
    goal(store, request="new")
    with pytest.raises(ConflictError):
        store.maintain_memory("one", generation)
    with store.engine.connect() as conn:
        for table in (db.nodes, db.assignments, db.logs, db.messages, db.summaries):
            assert conn.execute(select(table).where(table.c.generation_id == generation)).first() is None
    other.engine.dispose()


def test_multilingual_memory_budget_and_idempotent_action(pg_url):
    store = Store(pg_url)
    generation, root = setup(store)
    first = turn(store, generation, root, 1, text="记忆" * 4000)
    assert turn(store, generation, root, 1, text="记忆" * 4000) == first
    with pytest.raises(ConflictError):
        turn(store, generation, root, 1, text="different")
    context = store.memory_context("one", generation, "记忆", ChatScope(chat_id="chat-a"))
    assert context.truncated
    assert estimate(context.model_dump_json()) <= store.limits.context_tokens


def test_depth_saturation_is_visible_and_keeps_overflow_records(pg_url):
    store = Store(pg_url)
    generation, root = setup(store)
    store.limits = MemoryLimits(leaf_records=2, fanout=2, max_depth=1)
    for index in range(20):
        turn(store, generation, root, index)
        store.maintain_memory("one", generation)
    tree_invariants(store, 21, 2, 1)
    context = store.memory_context("one", generation, "sodium", ChatScope(chat_id="chat-a"))
    assert context.maintenance_saturated
