"""Storage-neutral memory commands. No SQL or model-provider dependencies."""
from datetime import datetime
from typing import Any

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
