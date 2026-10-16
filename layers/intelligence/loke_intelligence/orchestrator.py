"""Caller-owned structured memory and bounded, nonrecursive graph workers."""

import asyncio
import hashlib
import json
from typing import Protocol

from .orchestration_models import (
    OrchestrationInput,
    OrchestrationResult,
    PlannedActivity,
    RoutingProposal,
    SpecialistSnapshot,
    WorkerResult,
    WorkerTask,
)
from .orchestration_routing import (
    RoutingModel,
    clarify,
    local_route,
    routing_request,
    validate_route,
    validate_subject,
)
from .source_learning import plan_from_source_graph


def stable_id(kind: str, *parts: str) -> str:
    return kind + ":" + hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:24]


def specialist_id(learner_scope: str, graph_id: str) -> str:
    return stable_id("specialist", learner_scope, graph_id)


def worker_decision(task: WorkerTask):
    registration = task.registration
    validate_graph(registration)
    graph = registration.graph.model_copy(update={"goal_concept_ids": task.target.goal_concept_ids})
    return plan_from_source_graph(
        registration.document,
        graph,
        task.evaluated_at,
        task.study_minutes,
        allow_inferred=task.allow_inferred,
        events=registration.events,
        items=registration.items,
        progress=registration.progress,
    )


def validate_graph(registration):
    graph, document = registration.graph, registration.document
    if graph.document_id != document.id or graph.content_hash != document.content_hash:
        raise ValueError("Graph belongs to another document version.")
    collections = [graph.concepts, graph.relations, graph.citations]
    if any(len({value.id for value in values}) != len(values) for values in collections):
        raise ValueError("Graph IDs must be unique.")
    nodes, citations = {n.id for n in graph.concepts}, {c.id for c in graph.citations}
    for edge in graph.relations:
        if (
            edge.from_id not in nodes
            or edge.to_id not in nodes
            or not set(edge.citation_ids) <= citations
        ):
            raise ValueError("Graph edge has unknown references.")
    expected = hashlib.sha256(
        json.dumps(
            {
                "version": graph.version,
                "document_id": document.id,
                "concepts": [n.model_dump() for n in graph.concepts],
                "relations": [e.model_dump() for e in graph.relations],
                "citations": [c.model_dump() for c in graph.citations],
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    if expected != graph.graph_hash:
        raise ValueError("Graph fingerprint does not match its contents.")


class GraphWorkerPort(Protocol):
    async def run(self, task: WorkerTask) -> WorkerResult: ...


class GraphWorker:
    async def run(self, task: WorkerTask) -> WorkerResult:
        # Pure CPU work off the event loop; a timed-out thread has no persistence access.
        decision = await asyncio.to_thread(worker_decision, task)
        return WorkerResult(
            task_id=task.task_id,
            graph_id=task.registration.graph_id,
            graph_hash=task.registration.graph.graph_hash,
            decision=decision,
        )


PRIORITY = {
    "review_due": 0,
    "ungraded_answer": 1,
    "unchecked_prerequisite": 2,
    "incorrect_item": 3,
    "conflicting_items": 3,
    "assisted_retry": 3,
    "reported_hypothesis": 4,
    "goal_prerequisite": 5,
    "goal_check": 6,
    "goal_explanation": 7,
}


def merge_plans(results: list[WorkerResult], budget: int) -> list[PlannedActivity]:
    queues = {r.graph_id: list(r.decision.activities) for r in results if r.decision.activities}
    merged = []
    while queues and len(merged) < 3:

        def priority(gid):
            activity = queues[gid][0]
            rank = PRIORITY.get(activity.reason_code)
            if rank is None:  # Inferred prerequisite keeps the originating policy priority.
                rank = 2 if activity.reason_event_ids else 5
            return rank, gid

        graph_id = min(queues, key=priority)
        activity = queues[graph_id].pop(0)
        if activity.minutes > budget:
            del queues[graph_id]
            continue
        merged.append(
            PlannedActivity(
                graph_id=graph_id,
                activity_ref=stable_id("graph-activity", graph_id, activity.activity_id),
                activity=activity,
            )
        )
        budget -= activity.minutes
        if not queues[graph_id]:
            del queues[graph_id]
    return merged


def updated_snapshot(request, task, result, subjects, previous):
    graph = task.registration.graph
    concepts, edges, citations = set(), set(), set()
    if previous and previous.graph_hash == graph.graph_hash:
        concepts.update(set(previous.concept_ids) & {n.id for n in graph.concepts})
        edges.update(set(previous.edge_ids) & {e.id for e in graph.relations if e.usable})
        citations.update(set(previous.citation_ids) & {c.id for c in graph.citations})
    for activity in result.decision.activities:
        concepts.update([activity.concept_id, *activity.prerequisite_path])
        edges.update(activity.prerequisite_edge_ids)
        citations.update(activity.reason_source_ids)
    return SpecialistSnapshot(
        learner_scope=request.learner_scope,
        graph_id=task.registration.graph_id,
        specialist_id=specialist_id(request.learner_scope, task.registration.graph_id),
        graph_hash=graph.graph_hash,
        subjects=subjects
        or (previous.subjects if previous and previous.graph_hash == graph.graph_hash else []),
        concept_ids=sorted(concepts),
        edge_ids=sorted(edges),
        citation_ids=sorted(citations),
        evidence_ids=sorted(e.id for e in task.registration.events),
        progress_ids=sorted(p.activity_id for p in task.registration.progress),
    )


class GraphOrchestrator:
    def __init__(
        self,
        router: RoutingModel | None = None,
        worker: GraphWorkerPort | None = None,
        *,
        routing_timeout: float = 15,
        worker_timeout: float = 5,
    ):
        if not 0 < routing_timeout <= 15 or not 0 < worker_timeout <= 5:
            raise ValueError("Timeouts must be positive and within the 15s/5s limits.")
        self.router = router
        self.worker = worker or GraphWorker()
        self.routing_timeout = routing_timeout
        self.worker_timeout = worker_timeout

    async def run(self, request: OrchestrationInput) -> OrchestrationResult:
        # Isolate caller-owned objects from adapters, workers and returned snapshots.
        request = request.model_copy(deep=True)
        registrations = {g.graph_id: g for g in request.graphs}
        if len(registrations) != len(request.graphs):
            raise ValueError("Graph registration IDs must be unique.")
        snapshots = {s.graph_id: s for s in request.snapshots}
        if len(snapshots) != len(request.snapshots):
            raise ValueError("Specialist snapshots must be unique per graph.")
        for snapshot in request.snapshots:
            if (
                snapshot.learner_scope != request.learner_scope
                or snapshot.specialist_id != specialist_id(request.learner_scope, snapshot.graph_id)
            ):
                raise ValueError("Specialist snapshot belongs to another learner or identity.")
        for registration in request.graphs:
            graph = registration.graph
            if len(graph.concepts) > 24 or len(graph.relations) > 48:
                raise ValueError("Graph exceeds source-discovery limits.")
            previous = snapshots.get(registration.graph_id)
            if previous and previous.graph_hash == graph.graph_hash:
                for subject in previous.subjects:
                    if subject.graph_id != registration.graph_id:
                        raise ValueError("Snapshot subject belongs to another graph.")
                    validate_subject(subject, request)
        warnings = []
        origin = "confirmed" if request.confirmed_targets else "local"
        if self.router is not None and not request.confirmed_targets:
            try:
                summary = routing_request(request)
                if len(summary.model_dump_json()) > 12000:
                    raise ValueError("Routing context exceeds the model budget.")
                proposal = RoutingProposal.model_validate(
                    await asyncio.wait_for(
                        self.router.route(summary),
                        self.routing_timeout,
                    )
                )
                validate_route(proposal, request)
                origin = "model"
            except Exception:
                warnings.append(
                    "Routing proposal unavailable or invalid; used conservative local routing."
                )
                origin = "fallback"
                proposal = local_route(request)
        else:
            proposal = local_route(request)
        validate_route(proposal, request)
        if any(registrations[t.graph_id].graph.status != "ready" for t in proposal.targets):
            proposal = clarify("Resolve source coverage and confirm graph goals before planning.")
        if proposal.mode == "clarify":
            return OrchestrationResult(
                status="needs_clarification",
                mode="clarify",
                routing_origin=origin,
                snapshots=request.snapshots,
                warnings=warnings,
                clarification=proposal.clarification,
            )
        tasks = [
            WorkerTask(
                task_id=stable_id(
                    "graph-task",
                    request.learner_scope,
                    t.graph_id,
                    registrations[t.graph_id].graph.graph_hash,
                    *t.goal_concept_ids,
                ),
                learner_scope=request.learner_scope,
                registration=registrations[t.graph_id],
                target=t,
                study_minutes=request.study_minutes,
                evaluated_at=request.evaluated_at,
                allow_inferred=request.allow_inferred,
            )
            for t in sorted(proposal.targets, key=lambda t: t.graph_id)
        ]

        async def execute(task):
            try:
                result = WorkerResult.model_validate(
                    await asyncio.wait_for(
                        self.worker.run(task.model_copy(deep=True)),
                        self.worker_timeout,
                    )
                )
                if (result.task_id, result.graph_id, result.graph_hash) != (
                    task.task_id,
                    task.registration.graph_id,
                    task.registration.graph.graph_hash,
                ):
                    raise ValueError("Worker returned a different task or graph version.")
                # Workers cannot manufacture grades, findings, references, or teaching text.
                if result.decision != worker_decision(task):
                    raise ValueError("Worker result differs from authoritative source policy.")
                return result
            except Exception:
                return None

        if proposal.mode == "delegate":
            results = await asyncio.gather(*(execute(task) for task in tasks))
        else:
            results = [await execute(task) for task in tasks]
        successful = []
        for task, result in zip(tasks, results):
            if result is None:
                warnings.append(f"Graph task failed or timed out: {task.registration.graph_id}.")
                continue
            successful.append(result)
            gid = task.registration.graph_id
            subjects = [s for s in proposal.subjects if s.graph_id == gid]
            snapshots[gid] = updated_snapshot(request, task, result, subjects, snapshots.get(gid))
        activities = merge_plans(successful, request.study_minutes)
        status = (
            "failed"
            if not successful
            else "partial"
            if len(successful) != len(tasks)
            else "ready"
            if activities
            else "no_activity"
        )
        return OrchestrationResult(
            status=status,
            mode=proposal.mode,
            routing_origin=origin,
            activities=activities,
            workers=successful,
            snapshots=list(snapshots.values()),
            warnings=warnings,
        )
