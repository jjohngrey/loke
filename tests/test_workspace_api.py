import asyncio
import io
import wave

import pytest
from loke_contracts.models import LearningInput
from loke_intelligence.audio import validate_audio
from loke_memory.store import Store

from .test_learning_loop import HEADERS, save_goal


@pytest.fixture
def client(pg_url, monkeypatch):
    from fastapi.testclient import TestClient
    from loke_intelligence.app import create_app

    monkeypatch.setenv("MODEL_MODE", "demo")
    monkeypatch.setenv("SESSION_TOKEN", HEADERS["x-loke-session"])
    app = create_app(pg_url)
    with TestClient(app) as session:
        yield session


def test_workspace_chat_history_folder_restart_and_reset(client, pg_url):
    initial = save_goal(client)
    generation = initial["generation_id"]
    payload = dict(request_id="note", text="I studied sodium channels", scope={"chat_id": "notes"})
    assert client.post("/api/input", headers=HEADERS, json=payload).status_code == 200
    # Exact retry creates neither a second message pair nor a second evidence event.
    assert client.post("/api/input", headers=HEADERS, json=payload).status_code == 200
    folder = dict(request_id="folder", id="biology", name="Biology", generation_id=generation)
    assert client.post("/api/workspace/folder", headers=HEADERS, json=folder).status_code == 200
    settings = dict(
        request_id="move",
        id="notes",
        title="Channel notes",
        folder_id="biology",
        generation_id=generation,
    )
    assert client.post("/api/workspace/chat", headers=HEADERS, json=settings).status_code == 200
    reopened = Store(pg_url)
    workspace = reopened.workspace("demo-learner")
    assert workspace["folders"] == [dict(id="biology", name="Biology")]
    assert next(c for c in workspace["chats"] if c["id"] == "notes") == dict(
        id="notes", title="Channel notes", folder_id="biology"
    )
    history = reopened.chat_history("demo-learner", "notes", generation)
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][0]["text"] == payload["text"]
    assert not history["has_more"]
    assert reopened.workspace("other")["chats"] == []
    assert (
        reopened.chat_history("other", "notes", reopened.snapshot("other")["generation_id"])[
            "messages"
        ]
        == []
    )
    assert (
        client.delete(f"/api/learner?generation_id={generation}", headers=HEADERS).status_code
        == 200
    )
    assert reopened.workspace("demo-learner")["folders"] == []
    assert reopened.workspace("demo-learner")["chats"] == []
    assert (
        client.get(
            "/api/chats/history",
            headers=HEADERS,
            params=dict(chat_id="notes", generation_id=generation),
        ).status_code
        == 409
    )
    assert client.post("/api/workspace/folder", headers=HEADERS, json=folder).status_code == 409
    reopened.engine.dispose()


def test_history_paginates_without_losing_older_messages(client):
    initial = save_goal(client)
    coordinator = client.app.state.coordinator
    for i in range(52):
        asyncio.run(
            coordinator.input(
                "demo-learner",
                LearningInput(
                    request_id=f"page-{i}", text=f"Study note {i}", scope={"chat_id": "long"}
                ),
            )
        )
    params = dict(chat_id="long", generation_id=initial["generation_id"])
    page = client.get("/api/chats/history", headers=HEADERS, params=params).json()
    assert len(page["messages"]) == 100
    assert page["has_more"]
    earlier = client.get(
        "/api/chats/history",
        headers=HEADERS,
        params=dict(params, before=page["messages"][0]["sequence"]),
    ).json()
    assert len(earlier["messages"]) == 4
    assert not earlier["has_more"]
    assert [m["sequence"] for m in earlier["messages"] + page["messages"]] == list(range(1, 105))
    assert (
        client.get("/api/chats/history", headers=HEADERS, params=dict(params, before=0)).status_code
        == 422
    )


def test_attachment_preview_is_unsaved_until_explicit_input(client):
    assert (
        client.post(
            "/api/attachments/preview",
            headers=HEADERS,
            files={"file": ("note.md", b"# Sodium\nChannels open.")},
        ).status_code
        == 400
    )
    initial = save_goal(client)
    response = client.post(
        "/api/attachments/preview",
        headers=HEADERS,
        files={"file": ("note.md", b"# Sodium\nChannels open.")},
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview == dict(filename="note.md", text="# Sodium\nChannels open.", saved=False)
    unchanged = client.get("/api/view", headers=HEADERS).json()
    assert unchanged["state_revision"] == initial["state_revision"]
    assert unchanged["sources"] == []
    saved = client.post(
        "/api/input",
        headers=HEADERS,
        json=dict(
            request_id="attachment",
            text=preview["text"],
            mode="attachment",
                source_title=preview["filename"],
            scope={"chat_id": "files"},
        ),
    ).json()
    assert saved["events"][-1]["source"] == "attachment"
    assert saved["events"][-1]["assessment"] == "not_assessed"
    assert saved["sources"][0]["text"] == preview["text"]
    assert saved["sources"][0]["title"] == "note.md"
    assert (
        client.post("/api/attachments/preview", files={"file": ("note.txt", b"secret")}).status_code
        == 403
    )


@pytest.mark.parametrize(
    "filename,data",
    [
        ("bad.exe", b"binary"),
        ("empty.txt", b""),
        ("binary.txt", b"\x00"),
        ("large.txt", b"a" * 15001),
        ("bad.pdf", b"%PDF-bad"),
    ],
)
def test_bad_attachments_are_recoverable_without_writes(client, filename, data):
    initial = save_goal(client)
    assert (
        client.post(
            "/api/attachments/preview", headers=HEADERS, files={"file": (filename, data)}
        ).status_code
        == 400
    )
    assert (
        client.get("/api/view", headers=HEADERS).json()["state_revision"]
        == initial["state_revision"]
    )


def test_voice_preview_requires_consent_and_never_saves_itself(client, monkeypatch):
    initial = save_goal(client)

    async def fake_transcribe(data, filename):
        return "I studied membrane potentials"

    monkeypatch.setattr("loke_intelligence.app.transcribe", fake_transcribe)
    files = {"file": ("recording.wav", b"mock audio")}
    assert client.post("/api/audio/transcribe", headers=HEADERS, files=files).status_code == 400
    result = client.post(
        "/api/audio/transcribe", headers=dict(HEADERS, **{"audio-consent": "true"}), files=files
    )
    assert result.json() == dict(
        text="I studied membrane potentials", provenance="audio_transcription", saved=False
    )
    assert (
        client.get("/api/view", headers=HEADERS).json()["state_revision"]
        == initial["state_revision"]
    )
    saved = client.post(
        "/api/input",
        headers=HEADERS,
        json=dict(
            request_id="voice", text=result.json()["text"], mode="voice", scope={"chat_id": "voice"}
        ),
    ).json()
    assert saved["events"][-1]["source"] == "voice"
    assert saved["events"][-1]["assessment"] == "not_assessed"


def wav(seconds):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * int(seconds * 8000))
    return buffer.getvalue()


def test_real_audio_validation_rejects_corrupt_long_empty_and_mislabeled_clips():
    asyncio.run(validate_audio(wav(0.2), "clip.wav"))
    for data, filename in [
        (b"", "clip.wav"),
        (b"not audio", "clip.wav"),
        (wav(31), "clip.wav"),
        (wav(0.2), "clip.mp3"),
        (wav(0.2), "clip.exe"),
    ]:
        with pytest.raises(ValueError):
            asyncio.run(validate_audio(data, filename))


def test_capabilities_do_not_expose_keys(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert client.get("/api/capabilities", headers=HEADERS).json() == dict(
        audio_available=False, model_mode="demo"
    )


def test_transcription_returned_after_reset_is_discarded(client, monkeypatch):
    initial = save_goal(client)

    async def reset_during_transcription(data, filename):
        client.app.state.store.delete_learner("demo-learner", initial["generation_id"])
        return "Obsolete transcript"

    monkeypatch.setattr("loke_intelligence.app.transcribe", reset_during_transcription)
    response = client.post(
        "/api/audio/transcribe",
        headers=dict(
            HEADERS, **{"audio-consent": "true", "generation-id": initial["generation_id"]}
        ),
        files={"file": ("clip.wav", b"mock")},
    )
    assert response.status_code == 409
    assert client.get("/api/workspace", headers=HEADERS).json()["chats"] == []


def test_stale_preprocessing_generation_is_rejected_before_transcription(client, monkeypatch):
    initial = save_goal(client)

    def forbidden(*args):
        raise AssertionError("Stale audio must not reach a provider")

    monkeypatch.setattr("loke_intelligence.app.transcribe", forbidden)
    response = client.post(
        "/api/audio/transcribe",
        headers=dict(HEADERS, **{"audio-consent": "true", "generation-id": "stale"}),
        files={"file": ("clip.wav", b"mock")},
    )
    assert response.status_code == 409
    response = client.post(
        "/api/attachments/preview",
        headers=dict(HEADERS, **{"generation-id": "stale"}),
        files={"file": ("clip.txt", b"notes")},
    )
    assert response.status_code == 409
    assert (
        client.get("/api/view", headers=HEADERS).json()["state_revision"]
        == initial["state_revision"]
    )
