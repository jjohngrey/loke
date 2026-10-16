import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from loke_contracts.models import EvidenceEvent
from loke_intelligence.learning_models import ActivityProgress, AssessmentItem
from loke_intelligence.orchestration_models import (
    GraphRegistration,
    OrchestrationInput,
    RouteTarget,
    RoutingProposal,
    SubjectAssignment,
)
from loke_intelligence.orchestration_openrouter import OpenRouterRoutingModel
from loke_intelligence.orchestration_routing import routing_request
from loke_intelligence.orchestrator import GraphOrchestrator, GraphWorker, specialist_id
from loke_intelligence.source_discovery import discover_source_graph
from loke_intelligence.source_documents import ingest_source
from loke_intelligence.source_extractors import PatternGraphExtractor

TIME = datetime(2026, 10, 14, 4, tzinfo=UTC)


def registration(gid="physics", base="Force", goal="Acceleration"):
    document = ingest_source(
        (
            f"## {base}\n{base}: a source-defined foundation.\n\n"
            f"## {goal}\n{goal}: a source-defined change.\n"
            f"{base} is a prerequisite for {goal}.\n"
        ).encode(),
        f"{gid}.md",
    )
    graph = asyncio.run(discover_source_graph(document, f"Understand {goal}"))
    assert graph.status == "ready"
    return GraphRegistration(graph_id=gid, document=document, graph=graph)


def request(graphs=None, text="Acceleration", **kwargs):
    return OrchestrationInput(
        learner_scope="learner-a",
        text=text,
        graphs=graphs or [registration()],
        evaluated_at=kwargs.pop("evaluated_at", TIME),
        **kwargs,
    )


def target(registration):
    return RouteTarget(
        graph_id=registration.graph_id, goal_concept_ids=registration.graph.goal_concept_ids
    )


class Router:
    def __init__(self, proposal=None, error=None):
        self.proposal, self.error, self.calls = proposal, error, 0

    async def route(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return self.proposal


def run(value, **kwargs):
    return asyncio.run(GraphOrchestrator(**kwargs).run(value))


def test_direct_and_delegated_work_are_equivalent_and_stable():
    value = request()
    before = value.model_dump_json()
    direct = run(value)
    router = Router(RoutingProposal(mode="delegate", targets=[target(value.graphs[0])]))
    delegated = run(value, router=router)
    assert direct.mode == "direct" and delegated.mode == "delegate"
    assert direct.activities == delegated.activities
    assert direct.snapshots == delegated.snapshots
    assert direct.status == "ready"
    assert value.model_dump_json() == before
    repeated = run(value.model_copy(update={"snapshots": direct.snapshots}))
    assert repeated.snapshots == direct.snapshots
    assert direct.snapshots[0].specialist_id == specialist_id("learner-a", "physics")
    assert direct.snapshots[0].concept_ids and direct.snapshots[0].citation_ids
    assert not direct.snapshots[0].evidence_ids
    assert all(e.status == "unchecked" for e in direct.workers[0].decision.evidence)


def test_multi_graph_merge_is_deterministic_namespaced_and_budgeted():
    first = registration()
    second = registration("chemistry", "Atom", "Molecule")
    value = request([first, second], "Acceleration and Molecule", study_minutes=8)
    result = run(value)
    reversed_result = run(value.model_copy(update={"graphs": [second, first]}))
    assert result == reversed_result
    assert result.mode == "delegate"
    assert len(result.workers) == 2
    assert sum(a.activity.minutes for a in result.activities) <= 8
    assert len(result.activities) <= 3
    assert len({a.activity_ref for a in result.activities}) == len(result.activities)
    for gid in ["physics", "chemistry"]:
        selected = [a.activity for a in result.activities if a.graph_id == gid]
        worker = next(w for w in result.workers if w.graph_id == gid)
        assert selected == worker.decision.activities[: len(selected)]


def test_subject_inference_routes_physics_and_is_retained():
    value = request(text="Teach me physics")
    graph = value.graphs[0].graph
    subject = SubjectAssignment(
        graph_id="physics", label="physics", citation_ids=[graph.citations[0].id]
    )
    result = run(
        value,
        router=Router(
            RoutingProposal(
                mode="direct",
                targets=[target(value.graphs[0])],
                subjects=[subject],
            )
        ),
    )
    assert result.routing_origin == "model"
    assert result.snapshots[0].subjects == [subject]
    assert subject.inferred
    repeated = run(value.model_copy(update={"text": "Acceleration", "snapshots": result.snapshots}))
    assert repeated.snapshots[0].subjects == [subject]


def test_shared_concept_is_ambiguous_and_confirmation_resolves_it():
    first, second = registration(), registration("other-physics")
    previous = run(request([first])).snapshots
    value = request([first, second], snapshots=previous)
    result = run(value)
    assert result.status == "needs_clarification"
    assert result.snapshots == previous
    confirmed = run(value.model_copy(update={"confirmed_targets": [target(second)]}))
    assert confirmed.routing_origin == "confirmed"
    assert confirmed.workers[0].graph_id == "other-physics"


def test_model_cannot_bypass_ambiguous_graph_selection():
    first, second = registration(), registration("another-source")
    proposal = RoutingProposal(mode="direct", targets=[target(first)])
    result = run(request([first, second]), router=Router(proposal))
    assert result.status == "needs_clarification" and not result.snapshots


def test_ambiguous_inferred_subjects_require_clarification():
    first = registration()
    second = registration("other-physics", "Energy", "Power")
    subjects = [
        SubjectAssignment(
            graph_id=g.graph_id,
            label="physics",
            citation_ids=[g.graph.citations[0].id],
        )
        for g in [first, second]
    ]
    result = run(
        request([first, second], "Teach me physics"),
        router=Router(
            RoutingProposal(mode="direct", targets=[target(first)], subjects=subjects),
        ),
    )
    assert result.status == "needs_clarification" and not result.snapshots


@pytest.mark.parametrize("failure", [ValueError("invalid"), RuntimeError("provider")])
def test_provider_failure_uses_local_fallback(failure):
    router = Router(error=failure)
    result = run(request(), router=router)
    assert result.status == "ready" and result.routing_origin == "fallback"
    assert router.calls == 1 and result.warnings


@pytest.mark.parametrize(
    "kind", ["graph", "concept", "citation", "duplicate", "paraphrase", "extra"]
)
def test_invalid_model_proposals_fall_back_without_fabricated_memory(kind):
    value = request(text="unknown paraphrase" if kind == "paraphrase" else "Acceleration")
    graph = value.graphs[0].graph
    selected = target(value.graphs[0])
    proposal = RoutingProposal(mode="delegate", targets=[selected])
    if kind == "graph":
        proposal.targets[0].graph_id = "unknown"
    elif kind == "concept":
        proposal.targets[0].goal_concept_ids = ["unknown"]
    elif kind == "citation":
        proposal.subjects = [
            SubjectAssignment(graph_id="physics", label="physics", citation_ids=["unknown"])
        ]
    elif kind == "duplicate":
        proposal.targets.append(selected.model_copy())
    elif kind == "paraphrase":
        proposal.targets[0].goal_concept_ids = [
            next(n.id for n in graph.concepts if n.label == "Force")
        ]
    else:
        proposal = {**proposal.model_dump(), "grade": "correct"}
    result = run(value, router=Router(proposal))
    assert result.routing_origin == "fallback"
    if kind == "paraphrase":
        assert result.status == "needs_clarification" and not result.snapshots
    else:
        assert result.snapshots == run(value).snapshots


def test_more_than_three_graphs_clarifies_without_workers():
    graphs = [registration(str(i), f"Foundation {i}", f"Goal {i}") for i in range(4)]
    value = request(graphs, "Goal 0 and Goal 1 and Goal 2 and Goal 3")
    result = run(value)
    assert result.status == "needs_clarification" and not result.workers


def test_more_than_three_goals_clarifies():
    document = ingest_source(b"One: first.\nTwo: second.\nThree: third.\nFour: fourth.", "four.md")
    graph = asyncio.run(discover_source_graph(document, "Understand One"))
    value = request(
        [GraphRegistration(graph_id="four", document=document, graph=graph)], "One Two Three Four"
    )
    assert run(value).status == "needs_clarification"


def test_model_context_budget_falls_back_without_provider_call():
    value = request(text="Acceleration " + "x" * 13000)
    router = Router()
    result = run(value, router=router)
    assert router.calls == 0 and result.routing_origin == "fallback"


class SelectiveWorker:
    def __init__(self, bad_graph, kind="error"):
        self.bad_graph, self.kind = bad_graph, kind

    async def run(self, task):
        if task.registration.graph_id != self.bad_graph:
            return await GraphWorker().run(task)
        if self.kind == "timeout":
            await asyncio.sleep(1)
        if self.kind == "error":
            raise RuntimeError("secret provider text")
        result = await GraphWorker().run(task)
        if self.kind == "identity":
            result.graph_id = "wrong"
        elif self.kind == "citation":
            result.decision.activities[0].reason_source_ids = ["fabricated"]
        elif self.kind == "teaching":
            result.decision.activities[0].support_text = "Invented facts."
        return result


@pytest.mark.parametrize("kind", ["error", "timeout", "identity", "citation", "teaching"])
def test_partial_worker_failure_retains_failed_memory(kind):
    physics, chemistry = registration(), registration("chemistry", "Atom", "Molecule")
    previous = run(request([physics])).snapshots
    value = request([physics, chemistry], "Acceleration and Molecule", snapshots=previous)
    result = run(
        value,
        worker=SelectiveWorker("physics", kind),
        worker_timeout=0.01 if kind == "timeout" else 5,
    )
    assert result.status == "partial"
    assert [w.graph_id for w in result.workers] == ["chemistry"]
    assert next(s for s in result.snapshots if s.graph_id == "physics") == previous[0]
    assert "secret" not in " ".join(result.warnings)


def test_all_failures_and_clarification_leave_memory_unchanged():
    value = request()
    previous = run(value).snapshots
    value.snapshots = previous
    result = run(value, worker=SelectiveWorker("physics"))
    assert result.status == "failed" and not result.activities
    assert result.snapshots == previous
    value.text = "Unclear subject"
    assert run(value).snapshots == previous


def test_failed_memory_preserves_snapshot_order_for_multiple_graphs():
    physics, chemistry = registration(), registration("chemistry", "Atom", "Molecule")
    previous = [
        run(request([physics])).snapshots[0],
        run(request([chemistry], "Molecule")).snapshots[0],
    ]

    class FailingWorker:
        async def run(self, task):
            raise RuntimeError("failure")

    result = run(
        request([physics, chemistry], "Acceleration and Molecule", snapshots=previous),
        worker=FailingWorker(),
    )
    assert result.status == "failed" and result.snapshots == previous


def test_cancellation_propagates_without_snapshot_mutation():
    value = request()

    async def scenario():
        before = value.model_dump_json()
        entered = asyncio.Event()

        class Worker:
            async def run(self, task):
                entered.set()
                await asyncio.sleep(60)

        pending = asyncio.create_task(GraphOrchestrator(worker=Worker()).run(value))
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert value.model_dump_json() == before

    asyncio.run(scenario())


def test_router_timeout_and_cancellation():
    class SlowRouter:
        async def route(self, request):
            await asyncio.sleep(60)

    result = run(request(), router=SlowRouter(), routing_timeout=0.001)
    assert result.routing_origin == "fallback"
    value = request()

    async def scenario():
        pending = asyncio.create_task(GraphOrchestrator(router=SlowRouter()).run(value))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(scenario())


def test_delegation_is_concurrent_and_direct_is_serial():
    graphs = [registration(), registration("chemistry", "Atom", "Molecule")]

    class CountingWorker:
        active = 0
        peak = 0

        async def run(self, task):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.01)
                return await GraphWorker().run(task)
            finally:
                self.active -= 1

    for mode, peak in [("delegate", 2), ("direct", 1)]:
        worker = CountingWorker()
        router = Router(RoutingProposal(mode=mode, targets=[target(g) for g in graphs]))
        result = run(request(graphs), worker=worker, router=router)
        assert result.status == "ready" and worker.peak == peak


def test_graph_replacement_invalidates_findings_but_preserves_identity():
    previous = run(request()).snapshots[0]
    changed = registration("physics", "Energy", "Power")
    result = run(request([changed], "Power", snapshots=[previous]))
    snapshot = result.snapshots[0]
    assert snapshot.specialist_id == previous.specialist_id
    assert snapshot.graph_hash != previous.graph_hash
    assert not set(snapshot.concept_ids) & set(previous.concept_ids)
    assert not set(snapshot.citation_ids) & set(previous.citation_ids)


def test_learner_isolation_duplicate_inputs_and_aware_clock():
    value = request()
    snapshots = run(value).snapshots
    with pytest.raises(ValueError, match="another learner"):
        run(value.model_copy(update={"learner_scope": "learner-b", "snapshots": snapshots}))
    other = run(value.model_copy(update={"learner_scope": "learner-b"}))
    assert other.snapshots[0].specialist_id != snapshots[0].specialist_id
    with pytest.raises(ValueError, match="unique"):
        run(value.model_copy(update={"graphs": [value.graphs[0], value.graphs[0]]}))
    with pytest.raises(ValueError, match="unique"):
        run(value.model_copy(update={"snapshots": [snapshots[0], snapshots[0]]}))
    with pytest.raises(ValueError, match="timezone-aware"):
        request(evaluated_at=datetime(2026, 10, 14))


def test_progress_suppresses_completed_activity_without_assessment():
    value = request()
    first = run(value)
    activity = first.workers[0].decision.activities[0]
    value.graphs[0].progress = [
        ActivityProgress(activity_id=activity.activity_id, status="completed")
    ]
    value.snapshots = first.snapshots
    second = run(value)
    assert activity.activity_id not in {a.activity.activity_id for a in second.activities}
    assert second.snapshots[0].progress_ids == [activity.activity_id]
    assert all(e.status == "unchecked" for e in second.workers[0].decision.evidence)


def test_tampered_graph_citations_fail_without_memory_update():
    value = request()
    previous = run(value).snapshots
    value.snapshots = previous
    value.graphs[0].graph.citations[0].quote = "fabricated quote"
    result = run(value)
    assert result.status == "failed" and result.snapshots == previous


def test_graph_edges_and_document_versions_are_validated():
    for kind in ["edge", "document", "fingerprint"]:
        value = request()
        if kind == "edge":
            value.graphs[0].graph.relations[0].from_id = "unknown"
        elif kind == "document":
            value.graphs[0].document.content_hash = "different"
        else:
            value.graphs[0].graph.graph_hash = "different"
        assert run(value).status == "failed"


def test_authored_due_review_priority_evidence_references_and_no_answer_key():
    physics = registration()
    chemistry = registration("chemistry", "Atom", "Molecule")
    goal = chemistry.graph.goal_concept_ids[0]
    chemistry.items = [
        AssessmentItem(
            id="molecule-item",
            concept_id=goal,
            kind="mcq",
            prompt="Recall the authored answer.",
            options={"A": "First", "B": "Second"},
            answers=["a"],
            explanation="An authored explanation.",
        )
    ]
    chemistry.events = [
        EvidenceEvent(
            id="observed-answer",
            concept_id=goal,
            card_id="molecule-item",
            kind="quiz_answer",
            text="B",
            occurred_at=TIME - timedelta(hours=25),
            assessment="incorrect",
            assistance="none",
            source="quiz",
            grader="choice-rule-v1",
            expected_answer="a",
        )
    ]
    value = request([physics, chemistry], "Acceleration and Molecule", study_minutes=3)
    result = run(value)
    first = result.activities[0]
    assert first.graph_id == "chemistry" and first.activity.reason_code == "review_due"
    assert first.activity.reason_event_ids == ["observed-answer"]
    assert first.activity.support_text is None
    assert "answers" not in first.activity.card.model_dump()
    snapshot = next(s for s in result.snapshots if s.graph_id == "chemistry")
    assert snapshot.evidence_ids == ["observed-answer"]
    assert sum(a.activity.minutes for a in result.activities) <= 3
    # A graph cannot consume quiz evidence for another source's concept/item.
    physics.events = chemistry.events
    partial = run(value)
    assert partial.status == "partial"
    assert [w.graph_id for w in partial.workers] == ["chemistry"]


def test_inferred_edge_opt_out_reaches_the_existing_policy():
    async def scenario():
        document = ingest_source(
            b"Force: a foundation.\nAcceleration: a change.\nForce is related to Acceleration.",
            "inferred.md",
        )

        class Extractor:
            async def extract(self, request):
                proposal = await PatternGraphExtractor().extract(request)
                proposal.relations[0].kind = "prerequisite_of"
                proposal.relations[0].basis = "inferred"
                return proposal

        graph = await discover_source_graph(document, "Understand Acceleration", Extractor())
        value = OrchestrationInput(
            learner_scope="learner-a",
            text="Acceleration",
            evaluated_at=TIME,
            graphs=[GraphRegistration(graph_id="inferred", document=document, graph=graph)],
        )
        included = await GraphOrchestrator().run(value)
        excluded = await GraphOrchestrator().run(value.model_copy(update={"allow_inferred": False}))
        assert any(a.activity.reason_code == "inferred_prerequisite" for a in included.activities)
        assert all(not a.activity.prerequisite_edge_ids for a in excluded.activities)

    asyncio.run(scenario())


def test_minimum_budget_produces_no_activity_and_no_assessment():
    result = run(request(study_minutes=1))
    assert result.status == "no_activity" and not result.activities
    assert all(e.status == "unchecked" for e in result.workers[0].decision.evidence)


def test_offline_demo_scenarios():
    from loke_intelligence.orchestration_demo import SCENARIOS, run_scenario

    async def scenario():
        for name in SCENARIOS:
            result = await run_scenario(name)
            expected = "needs_clarification" if name == "ambiguous" else "ready"
            assert result["turns"][0]["status"] == expected
            assert len(result["turns"]) == (2 if name == "repeated" else 1)

    asyncio.run(scenario())


def test_unresolved_source_does_not_run_workers():
    value = request()
    value.graphs[0].graph.status = "needs_clarification"
    assert run(value).status == "needs_clarification"


def test_optional_openrouter_adapter_uses_one_bounded_strict_call(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    value = request()
    proposal = RoutingProposal(mode="delegate", targets=[target(value.graphs[0])])
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["max_tokens"] == 1200
        assert payload["response_format"]["json_schema"]["strict"]
        assert payload["provider"]["data_collection"] == "deny"
        assert request.extensions["timeout"]["read"] == 15
        assert "learner-a" not in payload["messages"][1]["content"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": proposal.model_dump_json()}}]}
        )

    result = run(value, router=OpenRouterRoutingModel(httpx.MockTransport(handler)))
    assert result.mode == "delegate" and result.routing_origin == "model"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response", [httpx.Response(500), httpx.Response(200, json={"choices": []})]
)
def test_adapter_http_and_malformed_errors_fall_back(monkeypatch, response):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    calls = []

    def handler(request):
        calls.append(request)
        return response

    result = run(request(), router=OpenRouterRoutingModel(httpx.MockTransport(handler)))
    assert result.routing_origin == "fallback" and result.status == "ready"
    assert len(calls) == 1


def test_adapter_requires_key_and_checks_budget_before_network(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert run(request(), router=OpenRouterRoutingModel()).routing_origin == "fallback"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    oversized = routing_request(request(text="x" * 13000))
    with pytest.raises(ValueError, match="12,000"):
        asyncio.run(OpenRouterRoutingModel().route(oversized))
