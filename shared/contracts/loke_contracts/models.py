from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatScope(Contract):
    chat_id: str = Field(default="default", min_length=1, max_length=100)
    project_id: str | None = Field(default=None, max_length=100)
    folder_path: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=8)
    concept_tags: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=24)
    node_tags: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=24)


class MemoryExcerpt(Contract):
    role: Literal["user", "assistant"] | None = None
    action_status: Literal["started", "succeeded", "failed", "cancelled", "committed"] | None = None
    record_id: str
    agent_id: str | None = None
    chat_id: str
    kind: Literal["interaction", "agent_log", "summary"]
    text: str
    observed_at: datetime
    reference_ids: list[str] = Field(default_factory=list)


class AgentMatch(Contract):
    agent_id: str
    root_id: str
    score: int
    record_ids: list[str]
    reasons: list[str]
    candidate_scan_truncated: bool = False


class MemoryContext(Contract):
    generation_id: str
    matches: list[AgentMatch] = Field(default_factory=list)
    recent: list[MemoryExcerpt] = Field(default_factory=list)
    summaries: list[MemoryExcerpt] = Field(default_factory=list)
    logs: list[MemoryExcerpt] = Field(default_factory=list)
    truncated: bool = False
    maintenance_saturated: bool = False


class WriteRequest(Contract):
    generation_id: str | None = Field(default=None, min_length=1, max_length=100)
    expected_state_revision: int | None = Field(default=None, ge=0)
    expected_plan_revision: int | None = Field(default=None, ge=0)


class GoalInput(WriteRequest):
    scope: ChatScope = Field(default_factory=ChatScope)
    request_id: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=3, max_length=500)
    storage_consent: bool
    reminders_enabled: bool = True
    study_minutes: int = Field(default=10, ge=3, le=30)


class LearningInput(WriteRequest):
    scope: ChatScope = Field(default_factory=ChatScope)
    request_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=15000)
    mode: Literal["text", "voice", "attachment"] = "text"
    source_title: str | None = Field(default=None, min_length=1, max_length=255)


class AnswerInput(WriteRequest):
    scope: ChatScope = Field(default_factory=ChatScope)
    request_id: str = Field(min_length=1, max_length=100)
    card_id: str
    answer: str = Field(min_length=1, max_length=200)


class ReminderSettings(WriteRequest):
    request_id: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool


class ClockAdvance(WriteRequest):
    request_id: str | None = Field(default=None, min_length=1, max_length=100)
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
    timestamp_provenance: Literal["wall_clock", "legacy_unverified"] = "wall_clock"
    projection_after: ConceptState | None = None
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
    generation_id: str = ""
    graph_version: str | None = None
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


class FolderInput(WriteRequest):
    request_id: str = Field(min_length=1, max_length=100)
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)


class WorkspaceFolder(Contract):
    id: str
    name: str


class ChatSettings(WriteRequest):
    request_id: str = Field(min_length=1, max_length=100)
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    folder_id: str | None = None


class ChatSummary(Contract):
    id: str
    title: str
    folder_id: str | None = None


class WorkspaceView(Contract):
    state_revision: int
    generation_id: str
    chats: list[ChatSummary]
    folders: list[WorkspaceFolder]
    has_more: bool = False


class ChatMessage(Contract):
    id: str
    sequence: int
    role: Literal["user", "assistant"]
    text: str
    observed_at: datetime


class HistoryPage(Contract):
    generation_id: str
    messages: list[ChatMessage]
    has_more: bool


class UploadPreview(Contract):
    text: str
    filename: str
    saved: Literal[False] = False


class AppCapabilities(Contract):
    audio_available: bool
    model_mode: str


class TopicProposal(Contract):
    concept_id: str | None
    explanation: str = Field(max_length=800)


class ContextBundle(Contract):
    context_truncated: bool = False
    memory: MemoryContext | None = None
    generation_id: str = ""
    graph_version: str | None = None
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
    workspace: WorkspaceView
    history: HistoryPage
    upload_preview: UploadPreview
    capabilities: AppCapabilities
    folder_input: FolderInput
    chat_settings: ChatSettings
