import asyncio
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from loke_contracts.side_threads import SideThreadRequest
from loke_intelligence.agent_runtime import ModelReply
from loke_intelligence.side_threads import SideThreadResponses, build_messages, stream_answer
from pydantic import ValidationError


def payload(**changes):
    return SideThreadRequest.model_validate({
        "generation_id": "generation", "thread_id": "thread", "request_id": "request",
        "anchor": {"chat_id": "main", "message_id": "source", "source_markdown": "$E=mc^2$\n```py\nx = 2\n```",
                   "selected_text": "mc2", "start_offset": 2, "end_offset": 5,
                   "stream_version": "loke-rendered-v1"},
        "main_history": [{"role": "user", "text": "Explain energy"},
                         {"role": "assistant", "text": "$E=mc^2$"}],
        "history": [{"role": "user", "text": "Why squared?"},
                    {"role": "assistant", "text": "Mass and energy are related."}],
        "question": "What does this mean?", **changes,
    })


class FakeModel:
    def __init__(self, result=None):
        self.requests = []
        self.result = result or ModelReply("Final answer")

    async def complete(self, messages, tools, **kwargs):
        self.requests.append((messages, tools, kwargs))
        kwargs["on_text_delta"]("Partial ")
        kwargs["on_text_delta"]("reply")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_context_keeps_original_math_and_code_separate_from_instructions_and_latest_question():
    request = payload()
    messages = build_messages(request)
    assert messages[0]["role"] == "system"
    context = json.loads(messages[1]["content"].split("\n", 1)[1])
    assert context["source_markdown"] == request.anchor.source_markdown
    assert context["selected_visible_text"] == "mc2"
    assert context["main_history_through_source"][-1]["content"] == "$E=mc^2$"
    assert [m["content"] for m in messages[2:-1]] == ["Why squared?", "Mass and energy are related."]
    assert sum(m["content"] == request.question for m in messages) == 1
    assert messages[-1] == {"role": "user", "content": request.question}


def test_context_bounds_histories_and_preserves_original_math_in_middle_of_long_source():
    request = payload(main_history=[{"role": "user", "text": "x" * 20000}] * 4,
                      history=[{"role": "assistant", "text": "y" * 20000}] * 4)
    request.anchor.source_markdown = "start" + "z" * 25000 + "$$E=mc^2$$" + "z" * 25000 + "$x^2$"
    request.anchor.start_offset = 42000
    messages = build_messages(request)
    context = json.loads(messages[1]["content"].split("\n", 1)[1])
    assert context["truncation"]["main_history"] and context["truncation"]["side_history"]
    assert context["source_markdown"] == request.anchor.source_markdown
    assert "$$E=mc^2$$" in context["source_markdown"]
    assert context["source_markdown"].startswith("start")
    assert context["source_markdown"].endswith("$x^2$")
    assert context["selected_visible_text"] == "mc2"


def test_stream_final_is_authoritative_and_does_not_use_tools_or_memory():
    async def scenario():
        model = FakeModel()
        events = [event async for event in stream_answer(model, payload())]
        assert [event.type for event in events] == ["delta", "delta", "completed"]
        assert events[-1].text == "Final answer"
        assert all(event.thread_id == "thread" and event.request_id == "request" for event in events)
        assert model.requests[0][1] == []
        assert model.requests[0][2]["tools_enabled"] is False
        model.requests[0][2]["on_text_delta"]("Late delta")
        assert len(events) == 3
    asyncio.run(scenario())


@pytest.mark.parametrize("result", [RuntimeError("private provider data"), ModelReply(""),
                                   ModelReply("x" * 6001), ModelReply("cut off", truncated=True)])
def test_failures_are_controlled_and_partial_output_is_not_completed(result):
    async def scenario():
        events = [event async for event in stream_answer(FakeModel(result), payload())]
        assert events[-1].type == "error"
        assert "private" not in events[-1].text
        assert not any(event.type == "completed" for event in events)
    asyncio.run(scenario())


def test_deadline_and_disconnect_invalidate_uncooperative_provider_callbacks():
    async def scenario():
        released = asyncio.Event()
        callbacks = []

        class Slow:
            async def complete(self, *args, **kwargs):
                callbacks.append(kwargs["on_text_delta"])
                try:
                    await released.wait()
                except asyncio.CancelledError:
                    await released.wait()
                kwargs["on_text_delta"]("stale")
                return ModelReply("stale")

        events = [event async for event in stream_answer(Slow(), payload(), timeout=.01)]
        assert events[-1].type == "error"
        callbacks[0]("late")
        released.set()
        await asyncio.sleep(.01)
        assert [event.type for event in events] == ["error"]

        started = asyncio.Event()
        class Streaming:
            async def complete(self, *args, **kwargs):
                kwargs["on_text_delta"]("first")
                started.set()
                await asyncio.sleep(10)
        generator = stream_answer(Streaming(), payload())
        assert (await anext(generator)).text == "first"
        await generator.aclose()
        await asyncio.sleep(0)
    asyncio.run(scenario())


def test_http_stream_is_ndjson_and_releases_request_capacity():
    model = FakeModel()
    responses = SideThreadResponses(model)
    app = FastAPI()
    @app.post("/reply")
    async def reply(request: SideThreadRequest):
        return responses.response(request)
    client = TestClient(app)
    response = client.post("/reply", json=payload().model_dump())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert json.loads(response.text.splitlines()[-1])["type"] == "completed"
    assert not responses.active
    invalid = payload().model_dump()
    invalid["question"] = " "
    assert client.post("/reply", json=invalid).status_code == 422


def test_same_thread_concurrency_capacity_and_reset_epoch_are_guarded():
    responses = SideThreadResponses(FakeModel())
    responses.response(payload())
    with pytest.raises(HTTPException) as conflict:
        responses.response(payload())
    assert conflict.value.status_code == 409
    for i in range(7):
        responses.response(payload(thread_id=f"thread-{i}"))
    with pytest.raises(HTTPException) as capacity:
        responses.response(payload(thread_id="excess"))
    assert capacity.value.status_code == 429
    epoch = responses.epoch
    responses.cancel_all()
    with pytest.raises(HTTPException) as reset:
        responses.response(payload(thread_id="new"), epoch)
    assert reset.value.status_code == 409


def test_contract_rejects_future_versions_bad_offsets_and_oversized_history():
    request = payload().model_dump()
    request["anchor"]["stream_version"] = "future"
    with pytest.raises(ValidationError):
        SideThreadRequest.model_validate(request)
    request = payload().model_dump()
    request["anchor"]["end_offset"] = request["anchor"]["start_offset"]
    with pytest.raises(ValidationError):
        SideThreadRequest.model_validate(request)
    with pytest.raises(ValidationError):
        payload(main_history=[{"role": "user", "text": "x" * 20000}] * 11)


def test_response_header_failure_releases_unstarted_reservation():
    async def scenario():
        responses = SideThreadResponses(FakeModel())
        response = responses.response(payload())
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            raise OSError("connection closed before headers")
        with pytest.raises(Exception):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert not responses.active
    asyncio.run(scenario())


def test_response_body_send_failure_cancels_provider_and_releases_capacity():
    async def scenario():
        cancelled = asyncio.Event()
        class Streaming:
            async def complete(self, *args, **kwargs):
                kwargs["on_text_delta"]("first")
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
        responses = SideThreadResponses(Streaming())
        response = responses.response(payload())
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("connection closed during body")
        with pytest.raises(Exception):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        await asyncio.wait_for(cancelled.wait(), .1)
        assert not responses.active
    asyncio.run(scenario())
