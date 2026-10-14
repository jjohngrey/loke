import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from loke_contracts.catalog import CARDS, CONCEPTS
from loke_contracts.models import (
    AnswerInput,
    ApiError,
    ClockAdvance,
    ContextBundle,
    GoalInput,
    LearningInput,
    LearningView,
    ReminderSettings,
    TopicProposal,
    TranscriptionResult,
)
from loke_intelligence.app import create_app
from loke_intelligence.openrouter import OpenRouterError
from loke_memory.store import Store

from tests.fakes import FakeMemory
from tests.fixture_scenarios import FIXTURES, GOAL, WRONG, scenarios, typescript_views


def read(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(params=["fake", "sqlite"])
def memory(request, tmp_path):
    adapter = (
        FakeMemory() if request.param == "fake" else Store(f"sqlite:///{tmp_path / 'port.db'}")
    )
    yield adapter
    if request.param == "sqlite":
        adapter.engine.dispose()


def test_published_views_match_coordinator_with_both_adapters(memory):
    pack = scenarios(memory)
    for name, view in pack["views"].items():
        assert read(f"views/{name}.json") == view, name
    assert read("context.json") == pack["context"]
    assert (FIXTURES / "views.ts").read_text() == typescript_views(pack["views"])


def test_fixtures_validate_and_have_real_cross_references():
    concepts = {c["id"] for c in CONCEPTS}
    cards = {c["id"]: c for c in CARDS}
    for path in (FIXTURES / "views").glob("*.json"):
        view = LearningView.model_validate_json(path.read_text())
        assert [c.model_dump() for c in view.concepts] == CONCEPTS
        events = {e.id: e for e in view.events}
        for event in view.events:
            assert event.occurred_at.utcoffset() is not None
            if event.concept_id:
                assert event.concept_id in concepts
            if event.card_id:
                assert cards[event.card_id]["concept_id"] == event.concept_id
        for state in view.states:
            assert state.concept_id in concepts
            assert all(events[e].concept_id == state.concept_id for e in state.evidence_ids)
        for activity in view.plan:
            assert activity.concept_id in concepts
            assert set(activity.reason_event_ids) <= events.keys()
        for notification in view.notifications:
            assert notification.reason_event_id in events
            assert notification.created_at.utcoffset() is not None
        if view.active_quiz:
            assert view.active_quiz.id in cards
            assert "answers" not in view.active_quiz.model_dump()
        assert sum(a.minutes for a in view.plan) <= 10
    requests = read("requests.json")
    GoalInput.model_validate(requests["goal"])
    for key in ("text", "voice", "attachment"):
        LearningInput.model_validate(requests[key])
    for key in (
        "wrong_answer",
        "ungraded_answer",
        "prerequisite_answer",
        "assisted_answer",
        "unassisted_answer",
    ):
        AnswerInput.model_validate(requests[key])
    ReminderSettings.model_validate(requests["reminders"])
    ClockAdvance.model_validate(requests["clock"])
    ContextBundle.model_validate(read("context.json"))
    TopicProposal.model_validate(read("proposal.json"))
    TranscriptionResult.model_validate(read("transcription.json"))
    for error in read("errors.json"):
        if error["status"] != 422:
            ApiError.model_validate(error["body"])


def test_memory_atomic_rollback_dedupe_and_isolation(memory):
    def commit(s):
        s["response"] = "Committed together"
        s["plan_revision"] += 1

    first = memory.mutate("one", "first", "payload", 0, commit)
    original = deepcopy(first)
    first["response"] = "Client mutation"
    assert memory.snapshot("one")["response"] == original["response"]
    memory.mutate("one", "second", "new", 1, commit)
    assert memory.mutate("one", "first", "payload", 0, commit) == original
    with pytest.raises(ValueError, match="different content"):
        memory.mutate("one", "first", "changed", None, commit)
    with pytest.raises(ValueError, match="changed"):
        memory.mutate("one", "stale", "stale", 0, commit)

    def fail(s):
        s["response"] = "Must roll back"
        s["sources"].append({"source_id": "rollback", "title": "Note", "text": "private"})
        raise ValueError("rollback")

    before = memory.snapshot("one")
    with pytest.raises(ValueError, match="rollback"):
        memory.mutate("one", "failure", "failure", 2, fail)
    assert memory.snapshot("one") == before
    # A failed transaction does not reserve its request ID.
    assert memory.mutate("one", "failure", "failure", 2, commit)["state_revision"] == 3
    assert memory.snapshot("two")["sources"] == []
    assert memory.retrieve_sources("two", "private") == []
    assert set(memory.learner_ids()) == {"one"}
    memory.delete_learner("one")
    assert memory.learner_ids() == []
    assert memory.mutate("one", "first", "new generation payload", 0, commit)["state_revision"] == 1


def test_http_examples_and_openapi(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_TOKEN", "fixture-token")
    monkeypatch.setenv("MODEL_MODE", "live")
    app = create_app(f"sqlite:///{tmp_path / 'http.db'}", "fixture-learner")
    headers = {"x-loke-session": "fixture-token"}

    async def failed_provider(*args):
        raise OpenRouterError(
            "Text provider did not return a valid proposal. Retry or use demo mode."
        )

    monkeypatch.setattr("loke_intelligence.coordinator.propose", failed_provider)
    with TestClient(app) as client:
        client.post("/api/goal", headers=headers, json=GOAL).raise_for_status()
        client.post("/api/quiz/answer", headers=headers, json=WRONG).raise_for_status()
        before = client.get("/api/view", headers=headers).json()
        for example in read("errors.json"):
            response = client.request(
                example["method"],
                example["path"],
                headers={} if example["status"] == 403 else headers,
                json=example["request"],
            )
            assert response.status_code == example["status"]
            assert response.json() == example["body"]
        assert client.get("/api/view", headers=headers).json() == before
        schema = client.get("/openapi.json").json()
        for path, operations in schema["paths"].items():
            if not path.startswith("/api/"):
                continue
            for operation in operations.values():
                expected = "TranscriptionResult" if path.endswith("/transcribe") else "LearningView"
                success = operation["responses"]["200"]["content"]["application/json"]["schema"]
                assert success["$ref"] == f"#/components/schemas/{expected}"
                assert operation["responses"]["409"]["content"]["application/json"]["schema"][
                    "$ref"
                ].endswith("/ApiError")


def test_transcription_example_is_unsaved_until_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_TOKEN", "fixture-token")
    monkeypatch.setenv("MODEL_MODE", "demo")
    app = create_app(f"sqlite:///{tmp_path / 'audio.db'}", "fixture-learner")
    headers = {"x-loke-session": "fixture-token", "audio-consent": "true"}
    example = read("transcription.json")

    async def mocked_transcription(data, filename):
        assert data == b"synthetic adapter input"
        assert filename == "sample.wav"
        return example["text"]

    monkeypatch.setattr("loke_intelligence.app.transcribe", mocked_transcription)
    with TestClient(app) as client:
        client.post("/api/goal", headers=headers, json=GOAL).raise_for_status()
        before = client.get("/api/view", headers=headers).json()
        response = client.post(
            "/api/audio/transcribe",
            headers=headers,
            files={"file": ("sample.wav", b"synthetic adapter input", "audio/wav")},
        )
        assert response.status_code == 200
        assert response.json() == example
        assert client.get("/api/view", headers=headers).json() == before
        response = client.post("/api/input", headers=headers, json=read("requests.json")["voice"])
        assert response.status_code == 200
        assert response.json()["events"][-1]["source"] == "voice"
        assert response.json()["events"][-1]["assessment"] == "not_assessed"
