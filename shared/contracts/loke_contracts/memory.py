"""Storage-neutral memory commands. No SQL or model-provider dependencies."""
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import Field

from .models import AgentMatch, ChatScope, Contract, MemoryContext, MemoryExcerpt  # noqa: F401


class ConflictError(ValueError):
    """A stale generation/version or reused request key cannot be committed."""


class CommitGuard(Contract):
    generation_id: str
    state_revision: int | None = Field(default=None, ge=0)
    plan_revision: int | None = Field(default=None, ge=0)
    graph_version: str | None = None


class JobLease(Contract):
    id: str
    learner_id: str
    generation_id: str
    kind: str
    token: str
    owner: str
    expires_at: datetime
    payload: dict[str, Any]


class MemoryTurn(Contract):
    scope: ChatScope = Field(default_factory=ChatScope)
    user_text: str = Field(max_length=15000)
    operation: str = Field(min_length=1, max_length=100)
    matched_agent_ids: list[str] = Field(default_factory=list, max_length=5)


class OperationalAction(Contract):
    operation: str = Field(default="action", min_length=1, max_length=100)
    status: Literal["started", "succeeded", "failed", "cancelled", "committed"] = "committed"
    tool_name: str | None = Field(default=None, max_length=100)
    tool_version: str | None = Field(default=None, max_length=100)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    matched_agent_ids: list[str] = Field(default_factory=list, max_length=5)


class MemorySnapshot(TypedDict):
    """Typed legacy wrapper; payload dictionaries remain during B's policy transition."""
    generation_id: str
    graph_version: str | None
    goal: str
    storage_consent: bool
    reminders_enabled: bool
    study_minutes: int
    agent_id: str | None
    response: str
    active_card_id: str | None
    assisted_concepts: list[str]
    state_revision: int
    plan_revision: int
    demo_clock_hours: int
    expires_at: str | None
    states: dict[str, dict[str, Any]]
    events: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    plan: list[dict[str, Any]]
    notifications: list[dict[str, Any]]
    review_jobs: list[dict[str, Any]]
    projection_checkpoint: NotRequired[dict[str, Any]]


LegacySnapshotTransform = Callable[[MemorySnapshot], None]
