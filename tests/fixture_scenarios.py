"""Reproducible baseline scenarios for A/C; no paid calls or application endpoints."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from loke_contracts.models import AnswerInput, ContextBundle, GoalInput, LearningInput
from loke_contracts.ports import MemoryPort
from loke_intelligence.coordinator import Coordinator

from tests.fakes import FakeMemory

FIXTURES = Path(__file__).resolve().parents[1] / "shared/fixtures/v1"
GOAL = dict(
    request_id="goal-1",
    goal="Understand neuronal transmitter release",
    storage_consent=True,
    reminders_enabled=True,
    study_minutes=10,
)
WRONG = dict(request_id="answer-1", card_id="ap-depolarization", answer="A")
NOTE = dict(
    request_id="note-1", text="Action potentials involve sodium and potassium.", mode="attachment"
)
BASE_TIME = datetime(2026, 10, 17, 1, tzinfo=UTC)


def scenarios(memory: MemoryPort) -> dict:
    """Same deterministic use cases can run against C's Store or a database-free fake."""
    service = Coordinator(memory)
    sequence = count()
    views = {}

    def capture(name, view):
        views[name] = view.model_dump(mode="json")

    def start():
        memory.delete_learner("fixture-learner")
        return service.goal("fixture-learner", GoalInput(**GOAL))

    def answer(payload):
        return service.answer("fixture-learner", AnswerInput(**payload))

    with (
        patch(
            "loke_intelligence.coordinator.uuid4",
            side_effect=lambda: uuid5(NAMESPACE_URL, f"loke-fixture:{next(sequence)}"),
        ),
        patch(
            "loke_intelligence.policy.now",
            side_effect=lambda s: BASE_TIME + timedelta(hours=s.get("demo_clock_hours", 0)),
        ),
        patch.dict("os.environ", {"DEMO_CLOCK_ENABLED": "true"}),
    ):
        capture("empty", service.view("fixture-learner"))
        capture("saved-goal", start())
        capture(
            "ungraded-answer",
            answer(
                dict(request_id="unsure-1", card_id="ap-depolarization", answer="I am not sure")
            ),
        )
        start()
        capture("wrong-answer", answer(WRONG))
        capture("due-reminder", service.advance_clock("fixture-learner", 24))
        memory.delete_learner("fixture-learner")
        capture("reset", service.view("fixture-learner"))
        start()
        answer(WRONG)
        answer(dict(request_id="prerequisite-1", card_id="resting-permeability", answer="K+"))
        capture(
            "assisted-correct",
            answer(dict(request_id="assisted-1", card_id="ap-repolarization", answer="A")),
        )
        start()
        capture(
            "unassisted-correct",
            answer(dict(request_id="correct-1", card_id="ap-depolarization", answer="B")),
        )
        start()
        capture("sources", asyncio.run(service.input("fixture-learner", LearningInput(**NOTE))))
        context_view = views["sources"]
        context = ContextBundle(
            **{
                k: context_view[k]
                for k in (
                    "learner_id",
                    "agent_id",
                    "goal",
                    "state_revision",
                    "plan_revision",
                    "concepts",
                    "states",
                    "events",
                    "sources",
                )
            }
        ).model_dump(mode="json")
    return {"views": views, "context": context}


def write_fixtures():
    """Explicit development command; replaces only published baseline fixture JSON."""
    pack = scenarios(FakeMemory())
    output = {f"views/{name}.json": view for name, view in pack["views"].items()}
    output["context.json"] = pack["context"]
    output["proposal.json"] = {
        "concept_id": "action_potential_phases",
        "explanation": "A recall question can check the reported studying.",
    }
    output["transcription.json"] = {
        "text": "I studied action potentials.",
        "provenance": "audio_transcription",
        "saved": False,
    }
    output["requests.json"] = {
        "goal": GOAL,
        "wrong_answer": WRONG,
        "attachment": NOTE,
        "ungraded_answer": {
            "request_id": "unsure-1",
            "card_id": "ap-depolarization",
            "answer": "I am not sure",
        },
        "prerequisite_answer": {
            "request_id": "prerequisite-1",
            "card_id": "resting-permeability",
            "answer": "K+",
        },
        "assisted_answer": {
            "request_id": "assisted-1",
            "card_id": "ap-repolarization",
            "answer": "A",
        },
        "unassisted_answer": {
            "request_id": "correct-1",
            "card_id": "ap-depolarization",
            "answer": "B",
        },
        "text": {"request_id": "text-1", "text": "I studied action potentials.", "mode": "text"},
        "voice": {"request_id": "voice-1", "text": "I studied action potentials.", "mode": "voice"},
        "reminders": {"enabled": False},
        "clock": {"hours": 24},
    }
    # Error payloads retain the current transport; 502/transcription are synthetic adapter examples.
    output["errors.json"] = [
        {
            "status": 400,
            "method": "POST",
            "path": "/api/goal",
            "request": dict(GOAL, storage_consent=False),
            "body": {"detail": "Consent is required to save your learning history."},
        },
        {
            "status": 403,
            "method": "GET",
            "path": "/api/view",
            "request": None,
            "body": {"detail": "Local session token is required."},
        },
        {
            "status": 409,
            "method": "POST",
            "path": "/api/quiz/answer",
            "request": dict(WRONG, answer="B"),
            "body": {"detail": "This request ID was already used for different content."},
        },
        {
            "status": 422,
            "method": "POST",
            "path": "/api/input",
            "request": {"request_id": "invalid-1", "text": ""},
            "body": {
                "detail": [
                    {
                        "type": "string_too_short",
                        "loc": ["body", "text"],
                        "msg": "String should have at least 1 character",
                        "input": "",
                        "ctx": {"min_length": 1},
                    }
                ]
            },
        },
        {
            "status": 502,
            "method": "POST",
            "path": "/api/input",
            "request": {"request_id": "provider-1", "text": "Action potentials"},
            "body": {
                "detail": "Text provider did not return a valid proposal. Retry or use demo mode."
            },
        },
    ]
    for relative, value in output.items():
        target = FIXTURES / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, indent=2) + "\n")
    (FIXTURES / "views.ts").write_text(typescript_views(pack["views"]))


def typescript_views(views: dict) -> str:
    """Contextual typing preserves discriminants that JSON imports widen to string."""
    lines = [
        "// Generated by python -m tests.fixture_scenarios; edit scenarios instead.",
        'import type { LearningView } from "@loke/contracts";',
        "export const views = {",
    ]
    lines.extend(f"  {json.dumps(name)}: {json.dumps(view)}," for name, view in views.items())
    lines.append("} satisfies Record<string, LearningView>;\n")
    return "\n".join(lines)


if __name__ == "__main__":
    write_fixtures()
