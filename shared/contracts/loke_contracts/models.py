from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoalInput(Contract):
    request_id: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=3, max_length=500)
    storage_consent: bool
    reminders_enabled: bool = True
    study_minutes: int = Field(default=10, ge=3, le=30)


class LearningInput(Contract):
    request_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=15000)
    mode: Literal["text", "voice", "attachment"] = "text"


class AnswerInput(Contract):
    request_id: str = Field(min_length=1, max_length=100)
    card_id: str
    answer: str = Field(min_length=1, max_length=200)


class ReminderSettings(Contract):
    enabled: bool


class ClockAdvance(Contract):
    hours: int = Field(default=24, ge=1, le=168)


class TranscriptionResult(Contract):
    text: str
    provenance: Literal["audio_transcription"] = "audio_transcription"
    saved: Literal[False] = False


class ApiError(Contract):
    # Validation (422) retains FastAPI's separate HTTPValidationError shape.
    detail: str


class Concept(Contract):
    id: str
    label: str
    aliases: list[str]
    prerequisites: list[str]
    resource_url: str


class QuizCard(Contract):
    id: str
    concept_id: str
    kind: Literal["mcq", "blank"]
    prompt: str
    options: dict[str, str] = Field(default_factory=dict)
    # No answers are sent to the frontend until assessment.


class ConceptState(Contract):
    concept_id: str
    status: Literal["unassessed", "needs_practice", "recent_unassisted_correct", "attempted"]
    evidence_ids: list[str]
    next_review_at: datetime | None = None


class EvidenceEvent(Contract):
    id: str
    card_id: str | None = None
    expected_answer: str | None = None
    grader: str | None = None
    concept_id: str | None
    kind: Literal["study_report", "quiz_answer"]
    text: str
    occurred_at: datetime
    assessment: Literal["not_assessed", "correct", "incorrect", "ungraded"]
    assistance: Literal["none", "after_explanation"]
    source: Literal["text", "voice", "attachment", "quiz"]


class NextActivity(Contract):
    kind: Literal["diagnostic", "practice", "review", "learn"]
    concept_id: str
    title: str
    reason: str
    reason_event_ids: list[str]
    minutes: int = 2


class Notification(Contract):
    id: str
    title: str
    reason_event_id: str
    created_at: datetime


class SourceChunk(Contract):
    source_id: str
    title: str
    text: str


class LearningView(Contract):
    learner_id: str
    goal: str
    storage_consent: bool
    reminders_enabled: bool
    agent_id: str | None
    state_revision: int
    plan_revision: int
    model_mode: str
    demo_clock_hours: int
    response: str
    plan: list[NextActivity]
    active_quiz: QuizCard | None
    states: list[ConceptState]
    concepts: list[Concept]
    events: list[EvidenceEvent]
    notifications: list[Notification]
    sources: list[SourceChunk]


class TopicProposal(Contract):
    concept_id: str | None
    explanation: str = Field(max_length=800)


class ContextBundle(Contract):
    learner_id: str
    agent_id: str | None
    goal: str
    state_revision: int
    plan_revision: int
    concepts: list[Concept]
    states: list[ConceptState]
    events: list[EvidenceEvent]
    sources: list[SourceChunk]


class ContractBundle(Contract):
    goal: GoalInput
    learning_input: LearningInput
    answer: AnswerInput
    reminders: ReminderSettings
    clock: ClockAdvance
    view: LearningView
    context: ContextBundle
    proposal: TopicProposal
    transcription: TranscriptionResult
    error: ApiError
