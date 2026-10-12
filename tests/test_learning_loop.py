import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from loke_contracts.models import GoalInput, LearningInput, TopicProposal
from loke_intelligence.app import create_app
from loke_intelligence.coordinator import Coordinator
from loke_memory.store import ConflictError, Store

HEADERS = {"x-loke-session": "local-demo-change-me"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "demo")
    monkeypatch.setenv("SESSION_TOKEN", HEADERS["x-loke-session"])
    monkeypatch.setenv("DEMO_CLOCK_ENABLED", "true")
    app = create_app(f"sqlite:///{tmp_path / 'learning.db'}")
    with TestClient(app) as client:
        yield client


def save_goal(client):
    response = client.post(
        "/api/goal",
        headers=HEADERS,
        json={
            "request_id": str(uuid4()),
            "goal": "Understand neuronal transmitter release",
            "storage_consent": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_consent_and_authorization(client):
    assert client.get("/api/view").status_code == 403
    response = client.post(
        "/api/input",
        headers=HEADERS,
        json={"request_id": "pre-consent", "text": "I studied action potentials"},
    )
    assert response.status_code == 400
    assert client.get("/api/view", headers=HEADERS).json()["events"] == []


def test_wrong_answer_changes_plan_and_replay_does_not_duplicate(client):
    initial = save_goal(client)
    assert initial["active_quiz"]["id"] == "ap-depolarization"
    assert "answers" not in initial["active_quiz"]
    payload = {"request_id": "answer-once", "card_id": "ap-depolarization", "answer": "A"}
    first = client.post("/api/quiz/answer", headers=HEADERS, json=payload)
    assert first.status_code == 200, first.text
    state = first.json()
    assert state["events"][-1]["assessment"] == "incorrect"
    assert state["plan"][0]["concept_id"] == "resting_potential"
    assert state["plan"][0]["reason_event_ids"] == [state["events"][-1]["id"]]
    assert state["agent_id"] == initial["agent_id"]
    replay = client.post("/api/quiz/answer", headers=HEADERS, json=payload)
    assert replay.json()["state_revision"] == state["state_revision"]
    assert len(client.get("/api/view", headers=HEADERS).json()["events"]) == 1
    payload["answer"] = "B"
    assert client.post("/api/quiz/answer", headers=HEADERS, json=payload).status_code == 409


def test_ambiguous_answer_and_stale_question_do_not_grade(client):
    save_goal(client)
    response = client.post(
        "/api/quiz/answer",
        headers=HEADERS,
        json={"request_id": "unsure", "card_id": "ap-depolarization", "answer": "I am not sure"},
    )
    assert response.json()["events"][-1]["assessment"] == "ungraded"
    assert response.json()["states"] == []
    response = client.post(
        "/api/quiz/answer",
        headers=HEADERS,
        json={"request_id": "wrong-card", "card_id": "calcium-trigger", "answer": "A"},
    )
    assert response.status_code == 400
    assert len(client.get("/api/view", headers=HEADERS).json()["events"]) == 1


def test_review_notification_is_durable_and_deduplicated(client):
    save_goal(client)
    client.post(
        "/api/quiz/answer",
        headers=HEADERS,
        json={"request_id": "wrong", "card_id": "ap-depolarization", "answer": "A"},
    )
    response = client.post("/api/demo/clock", headers=HEADERS, json={"hours": 24})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["notifications"]) == 1
    assert result["plan"][0]["kind"] == "review"
    client.app.state.coordinator.tick("demo-learner")
    assert len(client.get("/api/view", headers=HEADERS).json()["notifications"]) == 1
    assert result["notifications"][0]["reason_event_id"] == result["events"][-1]["id"]


def test_attachment_is_report_not_mastery_and_delete_clears_it(client):
    save_goal(client)
    response = client.post(
        "/api/input",
        headers=HEADERS,
        json={
            "request_id": "note",
            "mode": "attachment",
            "text": "Action potentials involve sodium and potassium.",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["events"][-1]["assessment"] == "not_assessed"
    assert result["states"] == []
    assert result["sources"]
    deleted = client.delete("/api/learner", headers=HEADERS).json()
    assert deleted["events"] == deleted["sources"] == deleted["notifications"] == []
    assert not deleted["storage_consent"]


def test_restart_and_learner_isolation(tmp_path):
    url = f"sqlite:///{tmp_path / 'restart.db'}"
    service = Coordinator(Store(url))
    first = service.goal(
        "one",
        GoalInput(request_id="goal", goal="Understand neural signaling", storage_consent=True),
    )
    asyncio.run(
        service.input(
            "one",
            LearningInput(request_id="note", text="Resting membrane potential", mode="attachment"),
        )
    )
    restarted = Coordinator(Store(url))
    assert restarted.view("one").agent_id == first.agent_id
    assert len(restarted.view("one").events) == 1
    assert restarted.view("two").events == []
    assert restarted.view("two").sources == []


def test_slow_model_proposal_cannot_overwrite_newer_goal(tmp_path, monkeypatch):
    service = Coordinator(Store(f"sqlite:///{tmp_path / 'stale.db'}"), "live")
    service.goal(
        "one",
        GoalInput(request_id="goal", goal="Understand neural signaling", storage_consent=True),
    )

    async def delayed_proposal(text, context):
        service.goal(
            "one",
            GoalInput(
                request_id="new-goal",
                goal="Understand neuronal calcium entry",
                storage_consent=True,
            ),
        )
        return TopicProposal(concept_id="action_potential_phases", explanation="Old proposal")

    monkeypatch.setattr("loke_intelligence.coordinator.propose", delayed_proposal)
    with pytest.raises(ConflictError):
        asyncio.run(
            service.input("one", LearningInput(request_id="stale-input", text="Action potential"))
        )
    assert service.view("one").goal == "Understand neuronal calcium entry"
    assert service.view("one").events == []


def test_intelligence_only_imports_memory_at_composition_root():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "layers/intelligence/loke_intelligence"
    for file in root.glob("*.py"):
        if file.name == "app.py":
            continue
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("loke_memory"), file.name


def test_disabled_reminders_do_not_dispatch(client):
    save_goal(client)
    client.post(
        "/api/quiz/answer",
        headers=HEADERS,
        json={"request_id": "missed", "card_id": "ap-depolarization", "answer": "A"},
    )
    client.post("/api/reminders", headers=HEADERS, json={"enabled": False})
    result = client.post("/api/demo/clock", headers=HEADERS, json={"hours": 24}).json()
    assert result["notifications"] == []


def test_assisted_correct_does_not_extend_review(client):
    save_goal(client)
    missed = client.post(
        "/api/quiz/answer",
        headers=HEADERS,
        json={"request_id": "missed", "card_id": "ap-depolarization", "answer": "A"},
    ).json()
    original_due = next(
        s for s in missed["states"] if s["concept_id"] == "action_potential_phases"
    )["next_review_at"]
    client.post(
        "/api/quiz/answer",
        headers=HEADERS,
        json={"request_id": "prerequisite", "card_id": "resting-permeability", "answer": "K+"},
    )
    correct = client.post(
        "/api/quiz/answer",
        headers=HEADERS,
        json={"request_id": "with-help", "card_id": "ap-repolarization", "answer": "A"},
    ).json()
    assert correct["events"][-1]["assistance"] == "after_explanation"
    assert (
        next(s for s in correct["states"] if s["concept_id"] == "action_potential_phases")[
            "next_review_at"
        ]
        == original_due
    )


def test_deleted_history_cannot_be_recreated_by_an_old_live_proposal(tmp_path, monkeypatch):
    service = Coordinator(Store(f"sqlite:///{tmp_path / 'delete-race.db'}"), "live")
    service.goal(
        "one",
        GoalInput(request_id="goal", goal="Understand neural signaling", storage_consent=True),
    )

    async def delayed_proposal(text, context):
        service.memory.delete_learner("one")
        service.goal(
            "one",
            GoalInput(
                request_id="new-goal", goal="Understand neural signaling", storage_consent=True
            ),
        )
        return TopicProposal(
            concept_id="action_potential_phases", explanation="Old deleted content"
        )

    monkeypatch.setattr("loke_intelligence.coordinator.propose", delayed_proposal)
    with pytest.raises(ValueError, match="reset"):
        asyncio.run(
            service.input("one", LearningInput(request_id="old-input", text="Action potential"))
        )
    assert service.view("one").events == []
