"""Bounded routing proposals and conservative offline graph selection."""

import re
from typing import Protocol

from .orchestration_models import (
    OrchestrationInput,
    RouteTarget,
    RoutingProposal,
    RoutingRequest,
    SubjectAssignment,
)


class RoutingModel(Protocol):
    async def route(self, request: RoutingRequest) -> RoutingProposal: ...


def phrase_matches(text: str, phrase: str) -> bool:
    words = re.findall(r"\w+", phrase.casefold())
    return bool(words) and bool(
        re.search(r"(?<!\w)" + r"\W+".join(map(re.escape, words)) + r"(?!\w)", text.casefold())
    )


def routing_request(request: OrchestrationInput) -> RoutingRequest:
    summaries = []
    for registration in sorted(request.graphs, key=lambda g: g.graph_id):
        graph = registration.graph
        summaries.append(
            dict(
                graph_id=registration.graph_id,
                graph_hash=graph.graph_hash,
                status=graph.status,
                goal_concept_ids=graph.goal_concept_ids,
                provisional_subjects=[
                    subject.model_dump()
                    for snapshot in request.snapshots
                    if snapshot.graph_id == registration.graph_id
                    and snapshot.graph_hash == graph.graph_hash
                    for subject in snapshot.subjects
                ],
                concepts=[n.model_dump() for n in graph.concepts],
                citations=[dict(id=c.id, quote=c.quote) for c in graph.citations],
            )
        )
    return RoutingRequest(text=request.text, graphs=summaries)


def clarify(message: str) -> RoutingProposal:
    return RoutingProposal(mode="clarify", clarification=message)


def local_route(request: OrchestrationInput) -> RoutingProposal:
    if request.confirmed_targets:
        targets = request.confirmed_targets
    else:
        targets = []
        phrase_graphs: dict[str, set[str]] = {}
        for registration in sorted(request.graphs, key=lambda g: g.graph_id):
            matched = []
            for node in registration.graph.concepts:
                for label in [node.label, *node.aliases]:
                    if phrase_matches(request.text, label):
                        normalized = " ".join(re.findall(r"\w+", label.casefold()))
                        phrase_graphs.setdefault(normalized, set()).add(registration.graph_id)
                        matched.append(node.id)
            if matched:
                if len(set(matched)) > 3:
                    return clarify("Narrow the request to at most three goals per graph.")
                targets.append(
                    RouteTarget(
                        graph_id=registration.graph_id, goal_concept_ids=sorted(set(matched))
                    )
                )
        if any(len(ids) > 1 for ids in phrase_graphs.values()):
            return clarify(
                "The topic matches multiple sources. Select the graph and goal concepts."
            )
    if not targets:
        return clarify("Select a graph and goal concept, or use a known concept label or alias.")
    if len(targets) > 3 or any(len(t.goal_concept_ids) > 3 for t in targets):
        return clarify("Narrow the request to at most three graphs and three goals per graph.")
    return RoutingProposal(mode="delegate" if len(targets) > 1 else "direct", targets=targets)


def validate_subject(subject: SubjectAssignment, request: OrchestrationInput) -> None:
    registrations = {g.graph_id: g for g in request.graphs}
    if subject.graph_id not in registrations:
        raise ValueError("Subject references an unknown graph.")
    registration = registrations[subject.graph_id]
    citations = {c.id: c for c in registration.graph.citations}
    pages = {p.number: p.text for p in registration.document.pages}
    for cid in subject.citation_ids:
        if cid not in citations:
            raise ValueError("Subject references an unknown citation.")
        citation = citations[cid]
        if (
            citation.document_id != registration.document.id
            or citation.page not in pages
            or not 0 <= citation.start < citation.end <= len(pages[citation.page])
            or pages[citation.page][citation.start : citation.end] != citation.quote
        ):
            raise ValueError("Subject citation does not match the supplied document.")


def validate_route(proposal: RoutingProposal, request: OrchestrationInput) -> None:
    registrations = {g.graph_id: g for g in request.graphs}
    if proposal.mode == "clarify":
        if proposal.targets or not proposal.clarification:
            raise ValueError("Clarification requires a question and no executable tasks.")
    elif not proposal.targets or proposal.clarification:
        raise ValueError("Executable routing requires targets and no clarification.")
    if len(proposal.targets) > 3:
        raise ValueError("Routing exceeds the three-worker limit.")
    ids = [t.graph_id for t in proposal.targets]
    if len(ids) != len(set(ids)):
        raise ValueError("Only one task per graph is allowed.")
    for target in proposal.targets:
        if target.graph_id not in registrations:
            raise ValueError("Routing references an unknown graph.")
        graph = registrations[target.graph_id].graph
        known = {n.id for n in graph.concepts}
        if len(target.goal_concept_ids) != len(set(target.goal_concept_ids)):
            raise ValueError("Goal concepts must be unique.")
        if not set(target.goal_concept_ids) <= known:
            raise ValueError("Routing references an unknown concept.")
        confirmed = {
            cid
            for t in request.confirmed_targets
            if t.graph_id == target.graph_id
            for cid in t.goal_concept_ids
        }
        allowed = (
            set(graph.goal_concept_ids)
            | confirmed
            | {
                n.id
                for n in graph.concepts
                if any(phrase_matches(request.text, label) for label in [n.label, *n.aliases])
            }
        )
        if not set(target.goal_concept_ids) <= allowed:
            raise ValueError("Model-only goal mapping requires confirmation.")
    subject_ids = [s.graph_id for s in proposal.subjects]
    if len(subject_ids) != len(set(subject_ids)):
        raise ValueError("Only one subject assignment per graph is allowed.")
    for subject in proposal.subjects:
        validate_subject(subject, request)
    if proposal.mode != "clarify" and not request.confirmed_targets:
        matched: dict[str, set[str]] = {}
        for registration in request.graphs:
            for node in registration.graph.concepts:
                for label in [node.label, *node.aliases]:
                    if phrase_matches(request.text, label):
                        normalized = " ".join(re.findall(r"\w+", label.casefold()))
                        matched.setdefault(normalized, set()).add(registration.graph_id)
        if any(len(graph_ids) > 1 for graph_ids in matched.values()):
            raise ValueError("Ambiguous concept matches require source confirmation.")
        if not matched:
            subjects = [
                *proposal.subjects,
                *[
                    subject
                    for snapshot in request.snapshots
                    if snapshot.graph_id in registrations
                    and snapshot.graph_hash == registrations[snapshot.graph_id].graph.graph_hash
                    for subject in snapshot.subjects
                ],
            ]
            for subject in subjects:
                for label in [subject.label, *subject.aliases]:
                    if phrase_matches(request.text, label):
                        normalized = " ".join(re.findall(r"\w+", label.casefold()))
                        matched.setdefault(normalized, set()).add(subject.graph_id)
            if any(len(graph_ids) > 1 for graph_ids in matched.values()):
                raise ValueError("Ambiguous subjects require source confirmation.")
