import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from loke_contracts.runtime import (
    MultipleChoiceInput,
    MultipleChoiceOutput,
    RunLimits,
    RuntimeRequest,
)
from loke_intelligence.agent_runtime import (
    AgentRuntime,
    InMemorySessionStore,
    ModelReply,
    ModelToolCall,
    RuntimeCapacity,
    RuntimeConflict,
    bounded_context,
)
from loke_intelligence.app import create_app
from loke_intelligence.runtime_model import OpenRouterRuntimeModel
from loke_intelligence.runtime_tools import ToolRegistry, example_registry

ARGUMENTS = {"question": "Where should we start?", "choices": [
    {"id": "a", "text": "An example"}, {"id": "b", "text": "An overview"},
    {"id": "c", "text": "A question"},
]}


def call(name="generate_multiple_choice_response", args=None, call_id="call-1"):
    return ModelToolCall(call_id, name, json.dumps(ARGUMENTS if args is None else args))


def request(request_id="one", text="Give me options", epoch=0):
    return RuntimeRequest(session_id="chat", request_id=request_id, text=text, session_epoch=epoch)


class FakeModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    async def complete(self, messages, tools, **kwargs):
        self.requests.append((messages, tools, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def engine(model, registry=None, **limits):
    return AgentRuntime(model, registry or example_registry(), InMemorySessionStore(), RunLimits(**limits))


async def finish(run):
    await run.task
    assert run.outcome
    assert run.events[-1].type == "outcome"
    assert [event.sequence for event in run.events] == list(range(len(run.events)))
    return run.outcome


def test_text_tool_observation_final_and_follow_up():
    async def scenario():
        model = FakeModel(ModelReply("A question first.", [call()]),
                          ModelReply("Choose an option.", prompt_tokens=21, completion_tokens=8),
                          ModelReply("Let's use an example."))
        runtime = engine(model)
        run = runtime.reserve("owner", request())
        result = await finish(run)
        assert result.status == "completed"
        assert result.text == "A question first.\nChoose an option."
        assert len(result.elements) == 1
        assert run.events[-2].type == "message_delta"
        assert next(event.element for event in run.events if event.type == "element") == result.elements[0]
        transcript = model.requests[1][0]
        assert transcript[-2]["tool_calls"][0]["id"] == transcript[-1]["tool_call_id"] == "call-1"
        assert json.loads(transcript[-1]["content"])["result"]["element"]["question"] == ARGUMENTS["question"]
        assert result.usage.model_calls == 2 and result.usage.tool_calls == 1
        assert result.usage.prompt_tokens == 21
        follow_up = await finish(runtime.reserve("owner", request("two", "Selected choice: An example")))
        assert follow_up.status == "completed"
        assert any(message.get("tool_call_id") == "call-1" for message in model.requests[2][0])
    asyncio.run(scenario())


@pytest.mark.parametrize("tool_call,code", [
    (call("unknown"), "unknown_tool"),
    (call(args={"question": "Q", "choices": []}), "invalid_arguments"),
    (call(args={**ARGUMENTS, "extra": 1}), "invalid_arguments"),
    (call(args={**ARGUMENTS, "question": " "}), "invalid_arguments"),
    (call(args={**ARGUMENTS, "choices": [ARGUMENTS["choices"][0]] * 3}), "invalid_arguments"),
    (ModelToolCall("call-1", "generate_multiple_choice_response", "{bad json"), "invalid_arguments"),
])
def test_tool_errors_are_observations(tool_call, code):
    async def scenario():
        model = FakeModel(ModelReply(tool_calls=[tool_call]), ModelReply("Recovered."))
        result = await finish(engine(model).reserve("owner", request()))
        assert result.status == "completed" and not result.elements
        assert json.loads(model.requests[1][0][-1]["content"])["error"]["code"] == code
    asyncio.run(scenario())


@pytest.mark.parametrize("failure,code", [("exception", "handler_error"), ("bad", "invalid_result"),
                                         ("denied", "permission_denied"), ("timeout", "tool_timeout"),
                                         ("large", "result_too_large")])
def test_handler_failures(failure, code):
    async def handler(payload, context):
        if failure == "exception":
            raise RuntimeError("private secret")
        if failure == "timeout":
            await asyncio.sleep(1)
        if failure == "large":
            payload = payload.model_copy(update={"question": "Q" * 500})
            element = await example_registry().specs["generate_multiple_choice_response"].handler(payload, context)
            return element
        return {"element": {"type": "multiple_choice", "choices": []}}

    async def scenario():
        spec = next(iter(example_registry().specs.values()))
        registry = ToolRegistry([replace(spec, handler=handler, timeout_seconds=0.01,
                                         permission=lambda context: failure != "denied",
                                         result_chars=256 if failure == "large" else 6000)])
        model = FakeModel(ModelReply(tool_calls=[call()]), ModelReply("Try a different approach."))
        result = await finish(engine(model, registry).reserve("owner", request()))
        assert not result.elements
        observation = model.requests[1][0][-1]["content"]
        assert json.loads(observation)["error"]["code"] == code
        assert "private secret" not in observation
    asyncio.run(scenario())


def test_data_only_results_and_sequential_tools():
    async def scenario():
        spec = next(iter(example_registry().specs.values()))
        registry = ToolRegistry([replace(spec, public_elements=lambda result: [])])
        model = FakeModel(ModelReply(tool_calls=[call(call_id="first"), call(call_id="second")]),
                          ModelReply("Observed both results."))
        result = await finish(engine(model, registry).reserve("owner", request()))
        assert result.status == "completed" and result.elements == []
        assert [m["tool_call_id"] for m in model.requests[-1][0] if m["role"] == "tool"] == ["first", "second"]
    asyncio.run(scenario())


def test_provider_error_and_budget_outcomes(monkeypatch, caplog):
    key = "test-error-credential"
    monkeypatch.setenv("OPENROUTER_API_KEY", key)

    async def scenario():
        result = await finish(engine(FakeModel(RuntimeError(f"Request rejected: {key}"))).reserve("owner", request()))
        assert result.reason == "provider_error" and result.status == "failed"
        assert key not in result.text and key not in caplog.text
        assert "[redacted API key]" in result.text
        model = FakeModel(ModelReply(tool_calls=[call()]), ModelReply("Still calling", [call(call_id="again")]))
        result = await finish(engine(model, model_calls=2, total_calls=3).reserve("owner", request()))
        assert result.status == "failed" and result.reason == "tool_budget"
        assert result.usage.model_calls + result.usage.tool_calls == 3
        assert model.requests[-1][2]["tools_enabled"] is False
        result = await finish(engine(FakeModel(ModelReply("x" * 101)), output_chars=100).reserve("owner", request()))
        assert result.reason == "output_budget"
    asyncio.run(scenario())


def test_repeated_failures_stop_and_finalize():
    async def scenario():
        model = FakeModel(ModelReply(tool_calls=[call("unknown")]),
                          ModelReply(tool_calls=[call("unknown", call_id="second")]),
                          ModelReply(tool_calls=[call("unknown", call_id="third")]))
        result = await finish(engine(model).reserve("owner", request()))
        assert result.status == "failed" and result.reason == "repeated_tool_errors"
        assert result.usage.tool_calls == 2
        assert model.requests[-1][2]["tools_enabled"] is False
    asyncio.run(scenario())


def test_repeated_errors_return_a_stop_reason_even_with_final_text():
    async def scenario():
        model = FakeModel(ModelReply(tool_calls=[call("unknown")]),
                          ModelReply(tool_calls=[call("unknown", call_id="second")]),
                          ModelReply("I can respond without options."))
        result = await finish(engine(model).reserve("owner", request()))
        assert result.status == "failed" and result.reason == "repeated_tool_errors"
        assert "I can respond without options." in result.text
        assert len(result.text) <= RunLimits().output_chars
    asyncio.run(scenario())


def test_context_and_output_limits_and_shutdown_are_terminal():
    async def scenario():
        runtime = engine(FakeModel(), context_chars=2000)
        result = await finish(runtime.reserve("owner", request(text="x" * 4000)))
        assert result.reason == "context_budget" and result.usage.model_calls == 0
        runtime = engine(FakeModel(ModelReply("x" * 100, [call()])), output_chars=100)
        result = await finish(runtime.reserve("owner", request()))
        assert result.reason == "output_budget" and len(result.text) <= 100
        runtime = engine(FakeModel(ModelReply("Unused")))
        run = runtime.reserve("owner", request())
        await runtime.shutdown()
        assert run.outcome.status == "cancelled"
    asyncio.run(scenario())


def test_duplicate_reservation_serialization_conflict_and_isolation():
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class SlowModel(FakeModel):
            async def complete(self, *args, **kwargs):
                started.set()
                await release.wait()
                return await super().complete(*args, **kwargs)

        model = SlowModel(ModelReply("First"), ModelReply("Second"), ModelReply("Other owner"))
        runtime = engine(model)
        first = runtime.reserve("owner", request())
        await started.wait()
        assert runtime.reserve("owner", request()) is first
        with pytest.raises(RuntimeConflict):
            runtime.reserve("owner", request(text="Different"))
        second = runtime.reserve("owner", request("two", "Follow up"))
        await asyncio.sleep(0)
        assert not model.requests
        release.set()
        await asyncio.gather(first.task, second.task)
        assert len(model.requests) == 2
        assert model.requests[1][0][-2]["content"] == "First"
        assert runtime.reserve("owner", request()).outcome == first.outcome
        await finish(runtime.reserve("other", request()))
        assert len(model.requests[-1][0]) == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["cancel", "reset", "deadline"])
@pytest.mark.parametrize("stage", ["provider", "handler"])
def test_cancellation_reset_deadline_and_late_suppression(operation, stage):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        late = asyncio.Event()

        async def slow():
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()  # An uncooperative external adapter finishes late.
            late.set()

        class SlowModel:
            async def complete(self, *args, **kwargs):
                if stage == "provider":
                    await slow()
                    return ModelReply("Late text")
                return ModelReply(tool_calls=[call()])

        async def handler(payload, context):
            await slow()
            return await example_registry().specs["generate_multiple_choice_response"].handler(payload, context)

        spec = next(iter(example_registry().specs.values()))
        registry = ToolRegistry([replace(spec, handler=handler)]) if stage == "handler" else example_registry()
        runtime = engine(SlowModel(), registry, deadline_seconds=0.05 if operation == "deadline" else 2.0)
        run = runtime.reserve("owner", request())
        await started.wait()
        if operation == "reset":
            assert runtime.reset("owner", "chat", 0) == 1
        elif operation == "cancel":
            runtime.cancel("owner", "chat", 0, "one")
        result = await asyncio.wait_for(finish(run), 0.3)
        assert result.status == ("failed" if operation == "deadline" else "cancelled")
        assert result.elements == []
        events = list(run.events)
        release.set()
        await late.wait()
        await asyncio.sleep(0)
        assert run.events == events
        assert "Late text" not in str(runtime.store.session("owner", "chat").conversation)
        if operation == "reset":
            assert runtime.store.session("owner", "chat").conversation == []
            with pytest.raises(RuntimeConflict):
                runtime.reserve("owner", request())
    asyncio.run(scenario())


def test_cancel_immediately_and_while_queued():
    async def scenario():
        runtime = engine(FakeModel(ModelReply("Unused")))
        first = runtime.reserve("owner", request())
        runtime.cancel("owner", "chat", 0, "one")
        result = await finish(first)
        assert result.status == "cancelled" and result.usage.model_calls == 0
        session = runtime.store.session("owner", "chat")
        await session.lock.acquire()
        queued = runtime.reserve("owner", request("two"))
        await asyncio.sleep(0)
        runtime.cancel("owner", "chat", 0, "two")
        assert (await finish(queued)).status == "cancelled"
        session.lock.release()
    asyncio.run(scenario())


def test_rapid_reset_and_same_request_id_in_new_epoch():
    async def scenario():
        runtime = engine(FakeModel(ModelReply("New session")))
        old = runtime.reserve("owner", request())
        assert runtime.reset("owner", "chat", 0) == 1
        assert runtime.reset("owner", "chat", 1) == 2
        new = runtime.reserve("owner", request(epoch=2))
        assert new is not old
        assert (await finish(old)).status == "cancelled"
        assert (await finish(new)).status == "completed"
        assert runtime.store.session("owner", "chat").conversation[0][0]["role"] == "user"
    asyncio.run(scenario())


def test_context_trims_complete_exchanges_and_store_bounds_history():
    exchange = [{"role": "assistant", "tool_calls": [call().message()]},
                {"role": "tool", "tool_call_id": "call-1", "content": "observation"}]
    groups = [[{"role": "user", "content": "x" * 2000}], exchange,
              [{"role": "user", "content": "Follow up"}]]
    context = bounded_context(groups, "instructions", [], 800)
    assert context[1:] == exchange + groups[-1]
    smaller = bounded_context(groups, "instructions", [], 150)
    assert smaller[1:] == groups[-1]
    with pytest.raises(RuntimeCapacity):
        bounded_context([groups[0]], "instructions", [], 150)

    async def scenario():
        runtime = engine(FakeModel(*[ModelReply("Response") for _ in range(5)]))
        runtime.store = InMemorySessionStore(max_sessions=1, max_outcomes=2, max_groups=3)
        for i in range(5):
            await finish(runtime.reserve("owner", request(str(i))))
        session = runtime.store.session("owner", "chat")
        assert len(session.runs) == 2 and len(session.conversation) == 3
        with pytest.raises(RuntimeCapacity):
            runtime.store.session("owner", "another")
    asyncio.run(scenario())


def test_authenticated_stream_replay_conflict_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "demo")
    monkeypatch.setenv("SESSION_TOKEN", "test-runtime-token")
    model = FakeModel(ModelReply("First", [call()]), ModelReply("Choose."), ModelReply("After reset"))
    runtime = engine(model)
    app = create_app(f"sqlite:///{tmp_path / 'api.db'}", agent_runtime=runtime)
    headers = {"x-loke-session": "test-runtime-token"}
    with TestClient(app) as client:
        payload = request().model_dump()
        assert client.post("/api/runtime/run", json=payload).status_code == 403
        first = client.post("/api/runtime/run", json=payload, headers=headers)
        assert first.status_code == 200 and first.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in first.text.splitlines()]
        assert events[-1]["outcome"]["status"] == "completed"
        assert len(events[-1]["outcome"]["elements"]) == 1
        assert client.post("/api/runtime/run", json=payload, headers=headers).text == first.text
        assert len(model.requests) == 2
        assert client.post("/api/runtime/run", json={**payload, "text": "Changed"}, headers=headers).status_code == 409
        assert client.post("/api/runtime/reset", headers=headers,
                           json={"session_id": "chat", "session_epoch": 0}).json()["session_epoch"] == 1
        assert client.post("/api/runtime/run", json=payload, headers=headers).status_code == 409
        response = client.post("/api/runtime/run", headers=headers, json=request("one", epoch=1).model_dump())
        assert json.loads(response.text.splitlines()[-1])["outcome"]["status"] == "completed"
        assert len(model.requests[-1][0]) == 2


def test_real_provider_adapter_tool_transcript_and_sanitized_errors(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-provider-token")
    monkeypatch.setenv("TEXT_MODEL", "meta/muse-wonder")
    monkeypatch.setenv("OPENROUTER_PROVIDER", "Meta")
    requests = []

    def transport(req):
        body = json.loads(req.content)
        requests.append(body)
        assert req.headers["authorization"] == "Bearer test-provider-token"
        assert "parallel_tool_calls" not in body
        assert body["provider"] == {
            "require_parameters": True, "data_collection": "deny", "only": ["Meta"],
        }
        if len(requests) == 1:
            message = {"role": "assistant", "content": "Before tool", "tool_calls": [call().message()]}
        else:
            assert body["messages"][-1]["tool_call_id"] == "call-1"
            assert json.loads(body["messages"][-1]["content"])["result"]["element"]["type"] == "multiple_choice"
            message = {"role": "assistant", "content": "Choose one"}
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}],
                                         "usage": {"prompt_tokens": 20, "completion_tokens": 10}})

    async def scenario():
        result = await finish(engine(OpenRouterRuntimeModel(httpx.MockTransport(transport))).reserve("owner", request()))
        assert result.status == "completed" and len(result.elements) == 1
        assert result.usage.prompt_tokens == 40
        assert requests[0]["tools"] == requests[1]["tools"]
        assert requests[0]["tools"][0]["function"]["parameters"]["additionalProperties"] is False
        adapter = OpenRouterRuntimeModel(httpx.MockTransport(lambda req: httpx.Response(401, text="test-provider-token")))
        result = await finish(engine(adapter).reserve("owner", request()))
        assert result.reason == "provider_error" and "token" not in result.text
    asyncio.run(scenario())


def test_example_schema_is_strict():
    assert MultipleChoiceInput.model_json_schema()["additionalProperties"] is False
    assert MultipleChoiceOutput.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("streamed", [True, False])
def test_unread_http_error_always_finishes_run(monkeypatch, streamed):
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")

    class ErrorBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"error":{"message":"No matching endpoint: offline-test-key"}}'

    async def scenario():
        response = httpx.Response(
            404, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            stream=ErrorBody(),
        )
        model = (OpenRouterRuntimeModel(httpx.MockTransport(lambda req: response)) if streamed
                 else FakeModel(httpx.HTTPStatusError("HTTP 404", request=response.request,
                                                       response=response)))
        run = engine(model).reserve("owner", request())
        outcome = await asyncio.wait_for(finish(run), 1)
        assert outcome.status == "failed" and outcome.reason == "provider_error"
        assert "404" in outcome.text
        assert "offline-test-key" not in outcome.text
        if streamed:
            assert "No matching endpoint" in outcome.text
        events = [event async for event in run.stream()]
        assert events[-1].outcome == outcome
    asyncio.run(scenario())


def test_streamed_error_body_keeps_transport_size_limit(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")
    chunks = []

    class LargeErrorBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(3):
                chunks.append(index)
                yield b"x" * 40000

    async def scenario():
        adapter = OpenRouterRuntimeModel(httpx.MockTransport(
            lambda req: httpx.Response(404, stream=LargeErrorBody()),
        ))
        outcome = await finish(engine(adapter).reserve("owner", request()))
        assert outcome.status == "failed" and outcome.reason == "provider_error"
        assert "transport limit" in outcome.text
        assert chunks == [0, 1]
    asyncio.run(scenario())
