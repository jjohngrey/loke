"""Database-free MemoryPort adapter. Never mount this in the application."""

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from loke_contracts.memory import ConflictError, MemoryContext
from loke_contracts.ports import MemoryPort


class FakeConflictError(ConflictError):
    """The baseline port exposes conflict semantics, not a concrete SQL exception."""


class FakeMemory(MemoryPort):
    def __init__(self):
        self.generations = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.actions = []
        self.outcomes: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}

    def learner_ids(self) -> list[str]:
        return list(self.records)

    def snapshot(self, learner_id: str) -> dict[str, Any]:
        self.generations.setdefault(learner_id, "generation-initial")
        return deepcopy(
            self.records.get(
                learner_id,
                dict(
                    goal="",
                    generation_id=self.generations[learner_id],
                    graph_version=None,
                    storage_consent=False,
                    reminders_enabled=False,
                    study_minutes=10,
                    agent_id=None,
                    response="Set one learning goal to begin.",
                    active_card_id=None,
                    assisted_concepts=[],
                    state_revision=0,
                    plan_revision=0,
                    demo_clock_hours=0,
                    expires_at=(datetime.now(UTC) + timedelta(days=7)).isoformat(),
                    states={},
                    events=[],
                    sources=[],
                    plan=[],
                    notifications=[],
                    review_jobs=[],
                ),
            )
        )

    def mutate(
        self,
        learner_id: str,
        request_id: str,
        fingerprint: str,
        expected_revision: int | None,
        transform: Callable[[dict[str, Any]], None],
        *, guard=None, operation="legacy", turn=None, legacy_fingerprint=None,
    ) -> dict[str, Any]:
        current = self.snapshot(learner_id)
        if guard and current["generation_id"] != guard.generation_id:
            raise FakeConflictError("Learning history was reset.")
        key = (learner_id, current["generation_id"], operation, request_id)
        if key in self.outcomes:
            prior_fingerprint, outcome = self.outcomes[key]
            if prior_fingerprint != fingerprint:
                raise FakeConflictError("This request ID was already used for different content.")
            return deepcopy(outcome)
        current = self.snapshot(learner_id)
        if expected_revision is not None and current["state_revision"] != expected_revision:
            raise FakeConflictError("Learning state changed. Retry with a new request ID.")
        if guard:
            for name in ("state_revision", "plan_revision", "graph_version"):
                expected = getattr(guard, name)
                if (expected is not None or name == "graph_version") and current.get(name) != expected:
                    raise FakeConflictError("Learning state changed.")
        # Transform an isolated copy: exceptions publish neither changes nor a dedupe outcome.
        before = deepcopy(current)
        transform(current)
        current["plan_revision"] = before["plan_revision"] + int(current["plan"] != before["plan"] or current["active_card_id"] != before["active_card_id"])
        current["state_revision"] += int(current != before or (turn is not None and current["storage_consent"]))
        self.records[learner_id] = deepcopy(current)
        self.outcomes[key] = (fingerprint, deepcopy(current))
        return deepcopy(current)

    def lookup_outcome(self, learner_id, request_id, fingerprint, generation_id, operation="legacy", legacy_fingerprint=None):
        if self.snapshot(learner_id)["generation_id"] != generation_id:
            raise FakeConflictError("Learning history was reset.")
        result = self.outcomes.get((learner_id, generation_id, operation, request_id))
        if result:
            if result[0] != fingerprint:
                raise FakeConflictError("This request ID was already used for different content.")
            return deepcopy(result[1])
        return None

    def memory_context(self, learner_id, generation_id, query, scope):
        return MemoryContext(generation_id=generation_id)

    def append_agent_log(self, *args, **kwargs):
        self.actions.append((args, kwargs))
        return "fake-action"

    def read_events(self, learner_id: str) -> list[dict[str, Any]]:
        return self.snapshot(learner_id)["events"]

    def read_sources(self, learner_id: str) -> list[dict[str, Any]]:
        return self.snapshot(learner_id)["sources"]

    def retrieve_sources(self, learner_id: str, query: str) -> list[dict[str, Any]]:
        # Independent baseline token-overlap implementation, with no memory-layer import.
        import re

        def tokens(text):
            return set(re.findall(r"[a-z0-9]+", text.lower()))

        words = tokens(query)
        ranked = [(len(words & tokens(s["text"])), s) for s in self.read_sources(learner_id)]
        return [s for score, s in sorted(ranked, key=lambda pair: pair[0], reverse=True) if score][
            :2
        ]

    def delete_learner(self, learner_id: str) -> None:
        self.records.pop(learner_id, None)
        from uuid import uuid4
        self.generations[learner_id] = str(uuid4())
        self.outcomes = {key: value for key, value in self.outcomes.items() if key[0] != learner_id}

    def expire(self) -> None:
        for learner_id in self.learner_ids():
            if datetime.fromisoformat(self.records[learner_id]["expires_at"]) <= datetime.now(UTC):
                self.delete_learner(learner_id)
