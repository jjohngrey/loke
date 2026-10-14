"""Policy-core inputs/outputs. These are not the application's HTTP/session contracts."""

from datetime import datetime
from typing import Literal

from loke_contracts.models import Concept, Contract, EvidenceEvent, QuizCard, SourceChunk
from pydantic import Field, field_validator, model_validator


class AssessmentItem(QuizCard):
    answers: list[str] = Field(min_length=1)
    explanation: str


class ActivityProgress(Contract):
    activity_id: str
    status: Literal["completed", "skipped"]


class PrerequisiteMetadata(Contract):
    edge_id: str
    prerequisite_id: str
    dependent_id: str
    basis: Literal["source_supported", "inferred"]
    source_ids: list[str] = Field(min_length=1)


class LearningContext(Contract):
    goal_concept_ids: list[str] = Field(min_length=1)
    concepts: list[Concept] = Field(min_length=1)
    items: list[AssessmentItem]
    events: list[EvidenceEvent] = Field(default_factory=list)
    sources: list[SourceChunk] = Field(default_factory=list, max_length=2)
    progress: list[ActivityProgress] = Field(default_factory=list)
    prerequisite_metadata: list[PrerequisiteMetadata] = Field(default_factory=list)
    graph_citation_ids: list[str] = Field(default_factory=list)
    reading_fallback: bool = False
    study_minutes: int = Field(default=10, ge=1, le=30)
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def aware_clock(cls, value):
        if value.utcoffset() is None:
            raise ValueError("Policy evaluation requires a timezone-aware clock.")
        return value


class ConceptEvidence(Contract):
    concept_id: str
    status: Literal[
        "unchecked",
        "uncertain",
        "needs_practice",
        "assisted_correct",
        "independent_correct",
        "conflicting",
    ]
    evidence_ids: list[str]
    report_ids: list[str]
    latest_event_id: str | None
    pending_answer_id: str | None
    next_review_at: datetime | None
    review_due: bool
    review_card_id: str | None
    review_reason_event_ids: list[str]


class SemanticCandidate(Contract):
    concept_id: str
    relevance: Literal["strong", "weak"]


class MisconceptionHypothesis(Contract):
    concept_id: str
    description: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    source_ids: list[str] = Field(default_factory=list, max_length=2)


class SemanticRequest(Contract):
    text: str = Field(min_length=1, max_length=15000)
    concepts: list[Concept] = Field(min_length=1)
    events: list[EvidenceEvent] = Field(default_factory=list, max_length=10)
    sources: list[SourceChunk] = Field(default_factory=list, max_length=2)


class SemanticInterpretation(Contract):
    status: Literal["matched", "ambiguous", "unmatched"]
    concept_id: str | None
    candidates: list[SemanticCandidate] = Field(max_length=3)
    hypotheses: list[MisconceptionHypothesis] = Field(default_factory=list, max_length=3)
    clarification: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def consistent_selection(self):
        ids = [candidate.concept_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("Semantic candidates must be unique.")
        if self.status == "matched":
            if self.concept_id is None or self.concept_id not in ids:
                raise ValueError("A match must select a supplied candidate.")
        elif self.concept_id is not None or self.hypotheses:
            raise ValueError("Unresolved interpretations cannot assert a concept or hypothesis.")
        if self.status == "unmatched" and self.candidates:
            raise ValueError("An unmatched interpretation has no candidates.")
        return self


class InterpretationResult(Contract):
    interpretation: SemanticInterpretation
    origin: Literal["aliases", "model", "fallback"]


class LearningActivity(Contract):
    activity_id: str
    kind: Literal["diagnostic", "practice", "review", "learn", "clarify"]
    concept_id: str
    card: QuizCard | None
    minutes: int
    reason_code: Literal[
        "review_due",
        "ungraded_answer",
        "unchecked_prerequisite",
        "incorrect_item",
        "conflicting_items",
        "assisted_retry",
        "reported_hypothesis",
        "goal_prerequisite",
        "goal_check",
        "goal_explanation",
        "inferred_prerequisite",
    ]
    reason: str
    reason_event_ids: list[str]
    reason_source_ids: list[str] = Field(default_factory=list)
    prerequisite_path: list[str] = Field(default_factory=list)
    prerequisite_edge_ids: list[str] = Field(default_factory=list)
    teaching_mode: Literal[
        "independent_recall",
        "clarify_response",
        "explain_then_check",
        "guided_practice",
        "explanation",
    ]
    support_text: str | None = None
    resource_url: str


class LearningDecision(Contract):
    policy_version: Literal["learning-policy-v1"] = "learning-policy-v1"
    status: Literal["ready", "needs_clarification", "no_activity"]
    evidence: list[ConceptEvidence]
    activities: list[LearningActivity]
    clarification: str | None = None
