import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from loke_contracts.runtime import (
    MultipleChoiceInput,
    MultipleChoiceOutput,
    RunLimits,
    RuntimeRequest,
)
from loke_intelligence import agent_runtime as runtime_module
from loke_intelligence.agent_runtime import (
    AgentRuntime,
    InMemorySessionStore,
    ModelReply,
    ModelToolCall,
    RuntimeCapacity,
    RuntimeConflict,
)
from loke_intelligence.runtime_errors import ModelFailure
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


@pytest.mark.parametrize("presentation", [None, "after_response", "inline"])
def test_choice_presentation_survives_tool_observation_and_event_replay(presentation):
    async def scenario():
        arguments = dict(ARGUMENTS)
        if presentation is not None:
            arguments["presentation"] = presentation
        model = FakeModel(ModelReply(tool_calls=[call(args=arguments)]),
                          ModelReply("An explanation before the follow-up."))
        run = engine(model).reserve("owner", request())
        result = await finish(run)
        expected = presentation or "after_response"
        assert result.status == "completed"
        assert result.elements[0].presentation == expected
        element_event = next(event for event in run.events if event.type == "element")
        assert element_event.element.presentation == expected
        assert run.events.index(element_event) < next(
            index for index, event in enumerate(run.events) if event.type == "message_delta"
        )
        observation = json.loads(model.requests[1][0][-1]["content"])
        assert observation["result"]["element"]["presentation"] == expected
    asyncio.run(scenario())


@pytest.mark.parametrize("tool_call,code", [
    (call("unknown"), "unknown_tool"),
    (call(args={"question": "Q", "choices": []}), "invalid_arguments"),
    (call(args={**ARGUMENTS, "extra": 1}), "invalid_arguments"),
    (call(args={**ARGUMENTS, "question": " "}), "invalid_arguments"),
    (call(args={**ARGUMENTS, "presentation": "unknown"}), "invalid_arguments"),
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
        secret = "private-prompt-or-upstream-credential"
        runtime = engine(FakeModel(RuntimeError(f"Request rejected: {key} {secret}")))
        run = runtime.reserve("owner", request())
        result = await finish(run)
        assert result.reason == "provider_error" and result.status == "failed"
        assert result.notice == ModelFailure.MESSAGES["unknown"]
        assert result.text == ""
        assert result.notice not in json.dumps(runtime.store.session("owner", "chat").conversation)
        observable = (result.model_dump_json() + caplog.text
                      + json.dumps([event.model_dump(mode="json") for event in run.events])
                      + json.dumps(runtime.store.session("owner", "chat").conversation))
        assert key not in observable and secret not in observable
        diagnostic = caplog.records[-1].runtime_diagnostic
        assert diagnostic["exception_type"] == "RuntimeError"
        assert diagnostic["run_id"] == run.run_id
        assert diagnostic["model_calls"] == 1 and diagnostic["tool_calls"] == 0
        assert diagnostic["frames"][-1]["function"] == "complete"
        assert diagnostic["elapsed_ms"] >= 0
        assert caplog.records[-1].exc_info is None
        model = FakeModel(ModelReply(tool_calls=[call()]), ModelReply("Still calling", [call(call_id="again")]))
        result = await finish(engine(model, model_calls=2, total_calls=3).reserve("owner", request()))
        assert result.status == "failed" and result.reason == "tool_budget"
        assert result.usage.model_calls + result.usage.tool_calls == 3
        assert model.requests[-1][2]["tools_enabled"] is False
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
    asyncio.run(scenario())


def test_shutdown_is_terminal():
    async def scenario():
        runtime = engine(FakeModel(ModelReply("Unused")))
        run = runtime.reserve("owner", request())
        await runtime.shutdown()
        assert run.outcome.status == "cancelled"
    asyncio.run(scenario())


@pytest.mark.parametrize("streamed", [False, True])
def test_long_chat_input_and_answers_survive_tools_and_follow_up_context(streamed):
    question = "Explain the universe. " * 2000
    answer = "A paragraph about the universe. " * 5000

    class LongModel(FakeModel):
        async def complete(self, *args, **kwargs):
            reply = await super().complete(*args, **kwargs)
            if streamed:
                for start in range(0, len(reply.text), 17000):
                    kwargs["on_text_delta"](reply.text[start:start + 17000])
                reply.text_streamed = True
            return reply

    async def scenario():
        model = LongModel(ModelReply(answer, [call()]), ModelReply("Choose an option."),
                          ModelReply("Next answer."))
        runtime = engine(model)
        run = runtime.reserve("owner", request(text=question))
        result = await finish(run)
        assert result.status == "completed" and result.notice is None
        assert result.text == answer + "\nChoose an option."
        assert len(result.elements) == 1
        assert model.requests[0][0][-1]["content"] == question
        assert any(message.get("content") == answer for message in model.requests[1][0])
        follow_up = await finish(runtime.reserve("owner", request("two", "Continue.")))
        assert follow_up.status == "completed"
        assert any(message.get("content") == answer for message in model.requests[2][0])
    asyncio.run(scenario())


@pytest.mark.parametrize("response_format", ["sse", "json"])
def test_large_provider_responses_finish_without_stream_or_answer_size_cutoffs(monkeypatch, response_format):
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")
    answer = "宇宙 has a long history. " * 6000
    if response_format == "json":
        body = json.dumps({"choices": [
            {"message": {"content": answer}, "finish_reason": "stop"},
        ]}).encode()
    else:
        events = [{"choices": [{"delta": {"reasoning": "r" * 100000}}]}]
        events.extend({"choices": [{"delta": {"content": answer[start:start + 100]}}]}
                      for start in range(0, len(answer), 100))
        events.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        body = ("".join(f"data: {json.dumps(event)}\n\n" for event in events)
                + "data: [DONE]\n\n").encode()

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for start in range(0, len(body), 4096):
                yield body[start:start + 4096]

    async def scenario():
        adapter = OpenRouterRuntimeModel(httpx.MockTransport(lambda req: httpx.Response(
            200, headers={"content-type": "application/json" if response_format == "json"
                          else "text/event-stream"}, stream=Chunks(),
        )))
        run = engine(adapter).reserve("owner", request())
        outcome = await finish(run)
        assert outcome.status == "completed" and outcome.notice is None
        assert outcome.text == answer
        assert "".join(event.message for event in run.events if event.type == "message_delta") == answer
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


@pytest.mark.parametrize("operation", ["cancel", "reset"])
@pytest.mark.parametrize("stage", ["provider", "handler"])
def test_cancellation_reset_and_late_suppression(operation, stage):
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
        runtime = engine(SlowModel(), registry)
        run = runtime.reserve("owner", request())
        await started.wait()
        if operation == "reset":
            assert runtime.reset("owner", "chat", 0) == 1
        elif operation == "cancel":
            runtime.cancel("owner", "chat", 0, "one")
        result = await asyncio.wait_for(finish(run), 0.3)
        assert result.status == "cancelled"
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


def test_response_can_continue_past_old_deadline_across_model_and_tool_calls(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(runtime_module, "time", SimpleNamespace(monotonic=lambda: clock.now))

    class LongResponseModel(FakeModel):
        async def complete(self, *args, **kwargs):
            clock.now += 40
            await asyncio.sleep(0.001)
            return await super().complete(*args, **kwargs)

    async def scenario():
        runtime = engine(LongResponseModel(ModelReply(tool_calls=[call()]),
                                           ModelReply("The full explanation.")))
        result = await finish(runtime.reserve("owner", request()))
        assert result.status == "completed"
        assert result.text == "The full explanation."
        assert result.usage.elapsed_ms == 80000
        assert result.usage.model_calls == 2 and result.usage.tool_calls == 1
    asyncio.run(scenario())


def test_provider_inactivity_preserves_partial_text_without_putting_notice_in_history():
    partial = "Our universe would be one bubble among potentially infinitely many."

    class InterruptedModel:
        async def complete(self, *args, **kwargs):
            kwargs["on_text_delta"](partial)
            raise ModelFailure("timeout")

    async def scenario():
        runtime = engine(InterruptedModel())
        run = runtime.reserve("owner", request())
        result = await finish(run)
        assert result.status == "failed" and result.reason == "provider_error"
        assert result.text == partial
        assert result.notice == ModelFailure.MESSAGES["timeout"]
        history = runtime.store.session("owner", "chat").conversation
        assert history[-1] == [{"role": "assistant", "content": partial}]
        assert result.notice not in json.dumps(history)
        assert [event async for event in run.stream()][-1].outcome == result
    asyncio.run(scenario())


def test_provider_read_inactivity_timeout_is_more_generous_than_connection_timeout(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")

    def transport(req):
        assert req.extensions["timeout"] == {"connect": 20, "read": 120, "write": 20, "pool": 20}
        return httpx.Response(200, json={"choices": [
            {"message": {"content": "A complete answer."}, "finish_reason": "stop"},
        ]})

    async def scenario():
        runtime = engine(OpenRouterRuntimeModel(httpx.MockTransport(transport)))
        result = await finish(runtime.reserve("owner", request()))
        assert result.status == "completed" and result.text == "A complete answer."
        assert result.notice is None
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


def test_store_bounds_history():
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
    from loke_intelligence.app import create_app

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
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "low")
    requests = []

    def transport(req):
        body = json.loads(req.content)
        requests.append(body)
        assert req.headers["authorization"] == "Bearer test-provider-token"
        assert "parallel_tool_calls" not in body
        assert body["provider"] == {
            "require_parameters": True, "data_collection": "deny", "only": ["Meta"],
        }
        assert "max_tokens" not in body
        assert "max_completion_tokens" not in body
        assert "max_output_tokens" not in body
        assert body["reasoning"] == {"effort": "low"}
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
    parameters = example_registry().declarations()[0]["function"]["parameters"]
    assert set(parameters["required"]) == set(parameters["properties"])


@pytest.mark.parametrize("streamed", [True, False])
def test_unread_http_error_always_finishes_run(monkeypatch, caplog, streamed):
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
        category = "routing" if streamed else "unknown"
        assert outcome.notice == ModelFailure.MESSAGES[category]
        assert "offline-test-key" not in outcome.text
        if streamed:
            assert caplog.records[-1].runtime_diagnostic["http_status"] == 404
        assert "No matching endpoint" not in outcome.text + caplog.text
        assert "offline-test-key" not in caplog.text
        events = [event async for event in run.stream()]
        assert events[-1].outcome == outcome
    asyncio.run(scenario())


@pytest.mark.parametrize("status, category", [
    (400, "rejected"), (401, "authentication"), (402, "credits"), (403, "authentication"),
    (404, "routing"), (408, "timeout"), (429, "rate_limit"), (500, "unavailable"),
    (503, "unavailable"), (504, "timeout"),
])
def test_provider_failures_have_safe_messages_and_structured_diagnostics(monkeypatch, caplog, status, category):
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured-secret")
    monkeypatch.setenv("TEXT_MODEL", "meta/muse-wonder")
    monkeypatch.setenv("OPENROUTER_PROVIDER", "Meta")
    secret = "upstream-secret-and-private-prompt"

    async def scenario():
        adapter = OpenRouterRuntimeModel(httpx.MockTransport(lambda req: httpx.Response(
            status, headers={"x-request-id": "req_123"},
            json={"error": {"code": status, "message": f"configured-secret Bearer {secret}",
                            "metadata": {"raw": secret}}},
        )))
        runtime = engine(adapter)
        run = runtime.reserve("owner", request())
        outcome = await finish(run)
        assert outcome.reason == "provider_error"
        assert outcome.notice == ModelFailure.MESSAGES[category]
        diagnostic = caplog.records[-1].runtime_diagnostic
        assert diagnostic["category"] == category
        assert diagnostic["http_status"] == diagnostic["provider_error_code"] == status
        assert diagnostic["provider_request_id"] == "req_123"
        assert diagnostic["model"] == "meta/muse-wonder" and diagnostic["provider"] == "Meta"
        assert diagnostic["tools_enabled"] is True
        assert diagnostic["require_parameters"] is True and diagnostic["data_collection"] == "deny"
        assert diagnostic["retry_count"] == 0
        assert "max_completion_tokens" not in diagnostic
        assert diagnostic["reasoning_effort"] == "provider_default"
        assert diagnostic["model_elapsed_ms"] >= 0
        assert diagnostic["run_id"] == run.run_id and diagnostic["frames"]
        observable = caplog.text + outcome.model_dump_json() + json.dumps(
            runtime.store.session("owner", "chat").conversation)
        assert secret not in observable and "configured-secret" not in observable
    asyncio.run(scenario())


@pytest.mark.parametrize("failure, category", [
    (httpx.ReadTimeout("private transport detail"), "timeout"),
    (httpx.ConnectError("private transport detail"), "transport"),
])
def test_provider_transport_failures_keep_diagnostics_without_exception_text(monkeypatch, caplog, failure, category):
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured-secret")

    def transport(req):
        raise failure

    async def scenario():
        outcome = await finish(engine(OpenRouterRuntimeModel(httpx.MockTransport(transport))).reserve("owner", request()))
        assert outcome.notice == ModelFailure.MESSAGES[category]
        assert caplog.records[-1].runtime_diagnostic["category"] == category
        assert caplog.records[-1].runtime_diagnostic["cause_type"] == type(failure).__name__
        assert caplog.records[-1].runtime_diagnostic["frames"][-1]["function"] == "transport"
        assert "private transport detail" not in outcome.text + caplog.text
    asyncio.run(scenario())


def test_provider_diagnostic_fields_are_bounded_and_do_not_copy_arbitrary_metadata(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured-secret")
    monkeypatch.setenv("TEXT_MODEL", "invalid model with private text")
    monkeypatch.setenv("OPENROUTER_PROVIDER", "configured-secret")

    async def scenario():
        for request_id in ("configured-secret", "id" * 100, "Bearer private-token"):
            adapter = OpenRouterRuntimeModel(httpx.MockTransport(lambda req: httpx.Response(
                404, headers={"x-request-id": request_id},
                json={"error": {"code": "private-error-code", "message": "private body"}},
            )))
            outcome = await finish(engine(adapter).reserve("owner", request()))
            assert outcome.notice == ModelFailure.MESSAGES["routing"]
            diagnostic = caplog.records[-1].runtime_diagnostic
            assert "provider_request_id" not in diagnostic and "provider_error_code" not in diagnostic
            assert diagnostic["model"] == diagnostic["provider"] == "[omitted]"
        assert all(value not in caplog.text for value in (
            "configured-secret", "private-token", "private-error-code", "private body", "invalid model",
        ))
    asyncio.run(scenario())


@pytest.mark.parametrize("body", [b"private malformed JSON", b'{"choices": []}',
                                  b'{"choices": [{"finish_reason": "length"}]}'])
def test_invalid_provider_response_has_controlled_failure(monkeypatch, caplog, body):
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured-secret")

    async def scenario():
        adapter = OpenRouterRuntimeModel(httpx.MockTransport(lambda req: httpx.Response(200, content=body)))
        outcome = await finish(engine(adapter).reserve("owner", request()))
        assert outcome.notice == ModelFailure.MESSAGES["invalid_response"]
        assert caplog.records[-1].runtime_diagnostic["category"] == "invalid_response"
        assert "private malformed JSON" not in outcome.text + caplog.text
    asyncio.run(scenario())


def test_provider_length_finish_reason_preserves_usage_diagnostics(monkeypatch, caplog):
    caplog.set_level("INFO", logger="loke_intelligence.runtime_model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured-secret")
    monkeypatch.delenv("OPENROUTER_REASONING_EFFORT", raising=False)
    event = json.dumps({
        "choices": [{"delta": {}, "finish_reason": "length"}],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 4096,
            "completion_tokens_details": {"reasoning_tokens": 4096},
        },
    })
    body = f"data: {event}\n\ndata: [DONE]\n\n".encode()

    async def scenario():
        adapter = OpenRouterRuntimeModel(httpx.MockTransport(lambda req: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body,
        )))
        outcome = await finish(engine(adapter).reserve("owner", request()))
        assert outcome.status == "failed" and outcome.reason == "provider_output_limit"
        assert outcome.notice == (
            "The model provider ended the response at its output limit."
        )
        assert outcome.text == ""
        assert outcome.usage.prompt_tokens == 120
        assert outcome.usage.completion_tokens == 4096
        diagnostic = next(
            record.runtime_model_diagnostic for record in caplog.records
            if hasattr(record, "runtime_model_diagnostic")
        )
        assert diagnostic["finish_reason"] == "length"
        assert diagnostic["stream_done"] is True
        assert diagnostic["prompt_tokens"] == 120
        assert diagnostic["completion_tokens"] == 4096
        assert diagnostic["reasoning_tokens"] == 4096
    asyncio.run(scenario())


def test_model_diagnostics_are_visible_with_default_server_logging():
    result = subprocess.run([sys.executable, "-c", """
import logging
import uvicorn

uvicorn.Config('loke_intelligence.app:app').configure_logging()
import loke_intelligence.app

logger = logging.getLogger('loke_intelligence.runtime_model')
assert logger.isEnabledFor(logging.INFO)
assert logger.hasHandlers()
logger.info('runtime_model_response startup-diagnostic')
"""], env={**os.environ, "MODEL_MODE": "demo", "DATABASE_URL": "sqlite:///:memory:"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "runtime_model_response startup-diagnostic" in result.stderr


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("partial", ["Partial answer", "x" * 120000])
def test_provider_truncated_replies_preserve_all_text_and_skip_tools(streamed, partial):
    class TruncatedModel:
        async def complete(self, messages, tools, **kwargs):
            if streamed:
                kwargs["on_text_delta"](partial)
            return ModelReply(partial, [call()], prompt_tokens=12, completion_tokens=50,
                              text_streamed=streamed, truncated=True)

    async def scenario():
        runtime = engine(TruncatedModel())
        run = runtime.reserve("owner", request())
        outcome = await finish(run)
        notice = "The model provider ended the response at its output limit."
        assert outcome.reason == "provider_output_limit" and outcome.status == "failed"
        assert outcome.text == partial
        assert outcome.notice == notice
        assert outcome.usage.prompt_tokens == 12 and outcome.usage.completion_tokens == 50
        assert outcome.usage.tool_calls == 0 and outcome.elements == []
        assert any(event.type == "message_delta" for event in run.events)
        history = runtime.store.session("owner", "chat").conversation
        assert not any("tool_calls" in message for group in history for message in group)
    asyncio.run(scenario())


def test_invalid_openrouter_reasoning_configuration_is_controlled(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured-secret")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "extreme")

    async def scenario():
        def unexpected_request(req):
            raise AssertionError("Invalid configuration must fail before the provider request.")

        outcome = await finish(engine(OpenRouterRuntimeModel(
            httpx.MockTransport(unexpected_request))).reserve("owner", request()))
        assert outcome.status == "failed" and outcome.reason == "provider_error"
        assert outcome.notice == ModelFailure.MESSAGES["configuration"]
        diagnostic = caplog.records[-1].runtime_diagnostic
        assert diagnostic["category"] == "configuration"
        assert diagnostic["configuration_field"] == "OPENROUTER_REASONING_EFFORT"
    asyncio.run(scenario())


def test_missing_provider_credentials_have_controlled_failure(monkeypatch, caplog):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    async def scenario():
        outcome = await finish(engine(OpenRouterRuntimeModel()).reserve("owner", request()))
        assert outcome.notice == ModelFailure.MESSAGES["configuration"]
        assert caplog.records[-1].runtime_diagnostic["category"] == "configuration"
    asyncio.run(scenario())


def test_oversized_error_body_keeps_original_provider_status_and_bounds_diagnostics(monkeypatch):
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
        assert outcome.notice == ModelFailure.MESSAGES["routing"]
        assert chunks == [0, 1]
    asyncio.run(scenario())
