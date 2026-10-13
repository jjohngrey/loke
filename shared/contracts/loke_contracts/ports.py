"""The intelligence layer depends on this boundary, not SQL implementation details."""

from collections.abc import Callable
from typing import Any, Protocol

from .models import LearningView


class MemoryPort(Protocol):
    """Current single-worker snapshot boundary; see shared/fixtures/README.md."""

    def learner_ids(self) -> list[str]: ...
    def snapshot(self, learner_id: str) -> dict[str, Any]: ...
    def mutate(
        self,
        learner_id: str,
        request_id: str,
        fingerprint: str,
        expected_revision: int | None,
        transform: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]: ...
    def read_events(self, learner_id: str) -> list[dict[str, Any]]: ...
    def read_sources(self, learner_id: str) -> list[dict[str, Any]]: ...
    def retrieve_sources(self, learner_id: str, query: str) -> list[dict[str, Any]]: ...
    def expire(self) -> None: ...
    def delete_learner(self, learner_id: str) -> None: ...


class LearningServicePort(Protocol):
    def view(self, learner_id: str) -> LearningView: ...
