"""Storage-neutral memory commands. No SQL or model-provider dependencies."""
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .models import Contract


class ConflictError(ValueError):
    """A stale generation/version or reused request key cannot be committed."""


class CommitGuard(Contract):
    generation_id: str
    state_revision: int | None = Field(default=None, ge=0)
    plan_revision: int | None = Field(default=None, ge=0)
    graph_version: str | None = None


class ChatScope(Contract):
    chat_id: str = Field(default="default", min_length=1, max_length=100)
    project_id: str | None = Field(default=None, max_length=100)
    folder_path: list[str] = Field(default_factory=list, max_length=8)
    concept_tags: list[str] = Field(default_factory=list, max_length=24)
    node_tags: list[str] = Field(default_factory=list, max_length=24)


class MemoryExcerpt(Contract):
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


class MemoryContext(Contract):
    generation_id: str
    matches: list[AgentMatch] = Field(default_factory=list)
    recent: list[MemoryExcerpt] = Field(default_factory=list)
    summaries: list[MemoryExcerpt] = Field(default_factory=list)
    logs: list[MemoryExcerpt] = Field(default_factory=list)
    truncated: bool = False


class JobLease(Contract):
    id: str
    learner_id: str
    generation_id: str
    kind: str
    token: str
    owner: str
    expires_at: datetime
    payload: dict[str, Any]
