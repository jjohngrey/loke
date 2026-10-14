"""Handoff from discovered graph to policy, preserving citations and uncertainty."""

from collections.abc import Sequence
from datetime import datetime

from loke_contracts.models import Concept, EvidenceEvent

from .learning_models import (
    ActivityProgress,
    AssessmentItem,
    LearningContext,
    LearningDecision,
    PrerequisiteMetadata,
)
from .learning_policy import choose_learning_activities
from .source_models import SourceDocument, SourceGraph


def plan_from_source_graph(
    document: SourceDocument,
    graph: SourceGraph,
    evaluated_at: datetime,
    study_minutes: int = 10,
    *,
    allow_inferred: bool = True,
    events: Sequence[EvidenceEvent] = (),
    items: Sequence[AssessmentItem] = (),
    progress: Sequence[ActivityProgress] = (),
) -> LearningDecision:
    if document.id != graph.document_id or document.content_hash != graph.content_hash:
        raise ValueError("Policy graph belongs to a different source document/version.")
    if graph.status != "ready" or not graph.goal_concept_ids:
        raise ValueError("Resolve source coverage/goal clarification before planning.")
    citations = {q.id: q for q in graph.citations}
    pages = {p.number: p.text for p in document.pages}
    for quote in graph.citations:
        if (
            quote.document_id != document.id
            or quote.page not in pages
            or quote.start < 0
            or quote.end > len(pages[quote.page])
            or quote.end <= quote.start
            or pages[quote.page][quote.start : quote.end] != quote.quote
        ):
            raise ValueError("Graph citation does not match this source's extracted page text.")
    concepts = {node.id: node for node in graph.concepts}
    prerequisites = {cid: [] for cid in concepts}
    metadata = []
    for edge in graph.relations:
        if (
            not edge.usable
            or edge.kind != "prerequisite_of"
            or (edge.basis == "inferred" and not allow_inferred)
        ):
            continue
        if edge.from_id not in concepts or edge.to_id not in concepts:
            raise ValueError("Policy edge references an unknown discovered concept.")
        if not set(edge.citation_ids) <= citations.keys():
            raise ValueError("Policy edge references unknown source citations.")
        prerequisites[edge.to_id].append(edge.from_id)
        metadata.append(
            PrerequisiteMetadata(
                edge_id=edge.id,
                prerequisite_id=edge.from_id,
                dependent_id=edge.to_id,
                basis=edge.basis,
                source_ids=edge.citation_ids,
            )
        )
    public_concepts = []
    for node in graph.concepts:
        if not node.citation_ids or not set(node.citation_ids) <= citations.keys():
            raise ValueError("Policy concept requires real source citations.")
        public_concepts.append(
            Concept(
                id=node.id,
                label=node.label,
                aliases=node.aliases,
                prerequisites=sorted(set(prerequisites[node.id])),
                resource_url=f"loke-source:{document.id}#{node.citation_ids[0]}",
            )
        )
    context = LearningContext(
        goal_concept_ids=graph.goal_concept_ids,
        concepts=public_concepts,
        items=list(items),
        events=list(events),
        progress=list(progress),
        prerequisite_metadata=metadata,
        graph_citation_ids=list(citations),
        reading_fallback=True,
        study_minutes=study_minutes,
        evaluated_at=evaluated_at,
    )
    decision = choose_learning_activities(context)
    if decision.activities and all(a.kind == "learn" for a in decision.activities):
        # Reading without a diagnostic goes from selected foundations to dependents.
        remaining = list(decision.activities)
        ordered = []
        while remaining:
            pending = {a.concept_id for a in remaining}
            ready = next(a for a in remaining if not (set(prerequisites[a.concept_id]) & pending))
            ordered.append(ready)
            remaining.remove(ready)
        decision.activities = ordered
    for activity in decision.activities:
        refs = sorted(
            set([*activity.reason_source_ids, *concepts[activity.concept_id].citation_ids])
        )
        activity.reason_source_ids = refs
        if activity.kind == "learn":
            # Quote the provided text, never synthesize an uncited teaching fact.
            content = [
                citations[ref].quote for ref in refs if not citations[ref].quote.startswith("#")
            ]
            activity.support_text = "\n".join(content) or citations[refs[0]].quote
    return decision
