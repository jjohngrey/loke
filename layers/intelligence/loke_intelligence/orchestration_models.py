"""Standalone orchestration contracts; not HTTP or database schemas."""

from datetime import datetime
from typing import Literal

from loke_contracts.models import Contract, EvidenceEvent
from pydantic import Field, field_validator

from .learning_models import ActivityProgress, AssessmentItem, LearningActivity, LearningDecision
from .source_models import DiscoveredConcept, SourceDocument, SourceGraph


class GraphRegistration(Contract):
    graph_id: str = Field(min_length=1, max_length=100)
    document: SourceDocument
    graph: SourceGraph
    events: list[EvidenceEvent] = Field(default_factory=list)
    items: list[AssessmentItem] = Field(default_factory=list)
    progress: list[ActivityProgress] = Field(default_factory=list)


class SubjectAssignment(Contract):
    graph_id: str
    label: str = Field(min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=6)
    citation_ids: list[str] = Field(min_length=1, max_length=6)
    inferred: Literal[True] = True


class RouteTarget(Contract):
    graph_id: str
    goal_concept_ids: list[str] = Field(min_length=1, max_length=3)


class RoutingProposal(Contract):
    mode: Literal["direct", "delegate", "clarify"]
    targets: list[RouteTarget] = Field(default_factory=list)
    subjects: list[SubjectAssignment] = Field(default_factory=list)
    clarification: str | None = Field(default=None, max_length=300)


class SpecialistSnapshot(Contract):
    learner_scope: str
    graph_id: str
    specialist_id: str
    graph_hash: str
    subjects: list[SubjectAssignment] = Field(default_factory=list)
    concept_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    progress_ids: list[str] = Field(default_factory=list)


class OrchestrationInput(Contract):
    learner_scope: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=15000)
    graphs: list[GraphRegistration] = Field(min_length=1)
    snapshots: list[SpecialistSnapshot] = Field(default_factory=list)
    confirmed_targets: list[RouteTarget] = Field(default_factory=list)
    study_minutes: int = Field(default=10, ge=1, le=30)
    evaluated_at: datetime
    allow_inferred: bool = True

    @field_validator("evaluated_at")
    @classmethod
    def aware_clock(cls, value):
        if value.utcoffset() is None:
            raise ValueError("Orchestration requires a timezone-aware clock.")
        return value


class RoutingCitation(Contract):
    id: str
    quote: str


class RoutingGraphSummary(Contract):
    graph_id: str
    graph_hash: str
    status: Literal["ready", "needs_clarification", "insufficient_source", "no_concepts"]
    goal_concept_ids: list[str]
    provisional_subjects: list[SubjectAssignment]
    concepts: list[DiscoveredConcept]
    citations: list[RoutingCitation]


class RoutingRequest(Contract):
    text: str = Field(min_length=1, max_length=15000)
    # Bounded graph summaries only: no learner history or complete documents.
    graphs: list[RoutingGraphSummary]


class WorkerTask(Contract):
    task_id: str
    learner_scope: str
    registration: GraphRegistration
    target: RouteTarget
    study_minutes: int
    evaluated_at: datetime
    allow_inferred: bool


class WorkerResult(Contract):
    task_id: str
    graph_id: str
    graph_hash: str
    decision: LearningDecision


class PlannedActivity(Contract):
    graph_id: str
    activity_ref: str
    activity: LearningActivity


class OrchestrationResult(Contract):
    status: Literal["ready", "partial", "needs_clarification", "failed", "no_activity"]
    mode: Literal["direct", "delegate", "clarify"]
    routing_origin: Literal["local", "model", "fallback", "confirmed"]
    activities: list[PlannedActivity] = Field(default_factory=list, max_length=3)
    workers: list[WorkerResult] = Field(default_factory=list)
    snapshots: list[SpecialistSnapshot]
    warnings: list[str] = Field(default_factory=list)
    clarification: str | None = None
