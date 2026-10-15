"""Server-side runtime adapters. Demo is deterministic; live uses OpenRouter."""

import asyncio
import json
import logging
import os
import re
import time
from typing import Callable

import httpx

from .agent_runtime import ModelReply, ModelToolCall
from .runtime_errors import ModelFailure

logger = logging.getLogger(__name__)

_KNOWN_FINISH_REASONS = {"stop", "tool_calls", "length", "content_filter", "function_call"}
_REASONING_EFFORTS = {"max", "xhigh", "high", "medium", "low", "minimal", "none"}


def _safe_finish_reason(value):
    if value is None:
        return "missing"
    if isinstance(value, str) and value in _KNOWN_FINISH_REASONS:
        return value
    return "other"


def _reasoning_effort():
    value = os.getenv("OPENROUTER_REASONING_EFFORT", "").strip().lower()
    if value and value not in _REASONING_EFFORTS:
        raise ModelFailure("configuration", configuration_field="OPENROUTER_REASONING_EFFORT")
    return value or None


def _usage_counts(usage, prompt_tokens, completion_tokens, reasoning_tokens):
    if not isinstance(usage, dict):
        return prompt_tokens, completion_tokens, reasoning_tokens
    for field in ("prompt_tokens", "completion_tokens"):
        value = usage.get(field)
        if value is not None:
            if type(value) is not int or value < 0:
                raise ModelFailure("invalid_response")
            if field == "prompt_tokens":
                prompt_tokens = value
            else:
                completion_tokens = value
    details = usage.get("completion_tokens_details")
    if details is not None:
        if not isinstance(details, dict):
            raise ModelFailure("invalid_response")
        value = details.get("reasoning_tokens")
        if value is not None:
            if type(value) is not int or value < 0:
                raise ModelFailure("invalid_response")
            reasoning_tokens = value
    return prompt_tokens, completion_tokens, reasoning_tokens


class DemoRuntimeModel:
    async def complete(self, messages, tools, *, tools_enabled, output_chars, on_text_delta=None):
        await asyncio.sleep(0.25)
        if messages[-1]["role"] == "tool":
            result = json.loads(messages[-1]["content"])
            return ModelReply(text="Choose an option to continue." if "result" in result
                              else "I couldn't prepare the options. What would you like to discuss?")
        text = next(message["content"] for message in reversed(messages) if message["role"] == "user")
        if text.startswith("Selected choice:"):
            return ModelReply(text=f"You chose {text.splitlines()[0][17:].strip()}. What topic should we explore?")
        if tools_enabled and any(word in text.lower() for word in ("choice", "quiz", "question", "options")):
            return ModelReply(text="Let's choose a starting point.", tool_calls=[ModelToolCall(
                "demo-choice", "generate_multiple_choice_response", json.dumps({
                    "question": "How would you like to explore this topic?",
                    "choices": [{"id": "example", "text": "Walk through an example"},
                                {"id": "overview", "text": "Start with an overview"},
                                {"id": "discuss", "text": "Discuss a specific question"}],
                }),
            )])
        return ModelReply(text="I'm ready to explore that with you. Ask for options to try a multiple-choice response.")


class OpenRouterRuntimeModel:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def complete(self, messages, tools, *, tools_enabled, output_chars, on_text_delta=None):
        started = time.monotonic()
        diagnostics = {
            "model": os.getenv("TEXT_MODEL", "openai/gpt-4.1-mini"),
            "provider": os.getenv("OPENROUTER_PROVIDER", "OpenAI"),
            "tools_enabled": tools_enabled,
            "require_parameters": True, "data_collection": "deny", "retry_count": 0,
        }
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        # These are configuration identifiers, never free-form provider diagnostics.
        for name in ("model", "provider"):
            value = diagnostics[name]
            if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", value) or (key and key in value):
                diagnostics[name] = "[omitted]"
        try:
            reasoning_effort = _reasoning_effort()
            diagnostics["reasoning_effort"] = reasoning_effort or "provider_default"
            reply = await self._complete(
                messages, tools, tools_enabled=tools_enabled,
                reasoning_effort=reasoning_effort,
                diagnostics=diagnostics, on_text_delta=on_text_delta,
            )
            diagnostics["model_elapsed_ms"] = int((time.monotonic() - started) * 1000)
            logger.info("runtime_model_response %s", json.dumps(diagnostics, sort_keys=True),
                        extra={"runtime_model_diagnostic": dict(diagnostics)})
            return reply
        except ModelFailure as exc:
            failure = exc
        except httpx.TimeoutException as exc:
            failure = ModelFailure("timeout", cause_type=type(exc).__name__).with_traceback(exc.__traceback__)
        except httpx.RequestError as exc:
            failure = ModelFailure("transport", cause_type=type(exc).__name__).with_traceback(exc.__traceback__)
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, AttributeError) as exc:
            failure = ModelFailure("invalid_response", cause_type=type(exc).__name__).with_traceback(exc.__traceback__)
        failure.diagnostics.update(diagnostics, model_elapsed_ms=int((time.monotonic() - started) * 1000))
        raise failure from None

    async def _complete(self, messages, tools, *, tools_enabled, reasoning_effort, diagnostics,
                        on_text_delta: Callable[[str], None] | None = None):
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ModelFailure("configuration")
        payload = {
            "model": os.getenv("TEXT_MODEL", "openai/gpt-4.1-mini"),
            "messages": messages, "tools": tools,
            "tool_choice": "auto" if tools_enabled else "none",
            # Leave the completion allowance to the provider/model, including reasoning.
            "stream": True,
            "stream_options": {"include_usage": True},
            "provider": {"require_parameters": True, "data_collection": "deny",
                         "only": [os.getenv("OPENROUTER_PROVIDER", "OpenAI")]},
        }
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            async with client.stream(
                "POST", "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"}, json=payload,
            ) as response:
                diagnostics["http_status"] = response.status_code
                request_id = response.headers.get("x-request-id", "")
                if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) and key not in request_id:
                    diagnostics["provider_request_id"] = request_id
                if not response.is_success:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 64000:
                            raise ModelFailure("response_size")
                    # Only numeric provider codes are admitted; messages and metadata can
                    # contain credentials, request content, and arbitrary upstream bodies.
                    try:
                        error = json.loads(body).get("error", {})
                        code = error.get("code") if isinstance(error, dict) else None
                        if type(code) is int and 100 <= code <= 599:
                            diagnostics["provider_error_code"] = code
                    except (ValueError, AttributeError):
                        pass
                    raise ModelFailure.from_status(response.status_code)

                content = []
                tool_deltas = {}
                prompt_tokens = completion_tokens = reasoning_tokens = None
                finish_reason = None
                stream_bytes = 0
                done_received = False
                data_events = choice_chunks = text_deltas = tool_call_deltas = 0
                usage_received = False
                if "application/json" in response.headers.get("content-type", ""):
                    response_format = "json"
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 64000:
                            raise ModelFailure("response_size")
                    data = json.loads(body)
                    usage = data.get("usage")
                    if isinstance(usage, dict):
                        usage_received = True
                        prompt_tokens, completion_tokens, reasoning_tokens = _usage_counts(
                            usage, prompt_tokens, completion_tokens, reasoning_tokens)
                    choices = data.get("choices") or []
                    if len(choices) != 1 or not isinstance(choices[0], dict):
                        raise ModelFailure("invalid_response")
                    choice = choices[0]
                    choice_chunks = 1
                    finish_reason = choice.get("finish_reason")
                    message = choice.get("message") or {}
                    if not isinstance(message, dict):
                        raise ModelFailure("invalid_response")
                    fragment = message.get("content") or ""
                    if not isinstance(fragment, str):
                        raise ModelFailure("invalid_response")
                    content.append(fragment)
                    text_deltas = int(bool(fragment))
                    if on_text_delta and fragment:
                        on_text_delta(fragment)
                    for index, call in enumerate(message.get("tool_calls") or []):
                        tool_call_deltas += 1
                        if not isinstance(call, dict):
                            raise ModelFailure("invalid_response")
                        function = call.get("function") or {}
                        if not isinstance(function, dict):
                            raise ModelFailure("invalid_response")
                        call_id = call.get("id")
                        name = function.get("name")
                        arguments = function.get("arguments")
                        if (call.get("type") != "function" or not isinstance(call_id, str)
                                or not isinstance(name, str) or not isinstance(arguments, str)):
                            raise ModelFailure("invalid_response")
                        tool_deltas[index] = {
                            "id": call_id, "type": "function", "name": name,
                            "arguments": arguments,
                        }
                else:
                    response_format = "sse"
                    async for line in response.aiter_lines():
                        stream_bytes += len(line.encode("utf-8")) + 1
                        if stream_bytes > 64000:
                            raise ModelFailure("response_size")
                        if not line.startswith("data:"):
                            continue
                        data_line = line[5:].strip()
                        if not data_line:
                            continue
                        if data_line == "[DONE]":
                            done_received = True
                            break
                        data_events += 1
                        data = json.loads(data_line)
                        usage = data.get("usage")
                        if isinstance(usage, dict):
                            usage_received = True
                            prompt_tokens, completion_tokens, reasoning_tokens = _usage_counts(
                                usage, prompt_tokens, completion_tokens, reasoning_tokens)
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        if len(choices) != 1 or not isinstance(choices[0], dict):
                            raise ModelFailure("invalid_response")
                        choice = choices[0]
                        choice_chunks += 1
                        if choice.get("finish_reason") is not None:
                            finish_reason = choice["finish_reason"]
                        delta = choice.get("delta") or {}
                        if not isinstance(delta, dict):
                            raise ModelFailure("invalid_response")
                        fragment = delta.get("content")
                        if fragment is not None:
                            if not isinstance(fragment, str):
                                raise ModelFailure("invalid_response")
                            content.append(fragment)
                            text_deltas += int(bool(fragment))
                            if on_text_delta and fragment:
                                on_text_delta(fragment)
                        for tool_delta in delta.get("tool_calls") or []:
                            tool_call_deltas += 1
                            if not isinstance(tool_delta, dict):
                                raise ModelFailure("invalid_response")
                            index = tool_delta.get("index")
                            if type(index) is not int or index < 0 or index > 16:
                                raise ModelFailure("invalid_response")
                            partial = tool_deltas.setdefault(index, {
                                "id": "", "type": None, "name": "", "arguments": "",
                            })
                            call_id = tool_delta.get("id")
                            call_type = tool_delta.get("type")
                            if call_id is not None:
                                if not isinstance(call_id, str):
                                    raise ModelFailure("invalid_response")
                                partial["id"] += call_id
                            if call_type is not None:
                                if not isinstance(call_type, str):
                                    raise ModelFailure("invalid_response")
                                partial["type"] = call_type
                            function = tool_delta.get("function") or {}
                            if not isinstance(function, dict):
                                raise ModelFailure("invalid_response")
                            for field in ("name", "arguments"):
                                value = function.get(field)
                                if value is not None:
                                    if not isinstance(value, str):
                                        raise ModelFailure("invalid_response")
                                    partial[field] += value
                finish_reason_label = _safe_finish_reason(finish_reason)
                diagnostics.update({
                    "response_format": response_format,
                    "response_bytes": len(body) if response_format == "json" else stream_bytes,
                    "sse_data_events": data_events,
                    "choice_chunks": choice_chunks,
                    "text_delta_count": text_deltas,
                    "content_chars": sum(map(len, content)),
                    "tool_call_deltas": tool_call_deltas,
                    "tool_call_count": len(tool_deltas),
                    "finish_reason": finish_reason_label,
                    "finish_reason_state": "recognized" if finish_reason_label in _KNOWN_FINISH_REASONS
                    else finish_reason_label,
                    "stream_done": done_received if response_format == "sse" else None,
                    "usage_received": usage_received,
                })
                if prompt_tokens is not None:
                    diagnostics["prompt_tokens"] = prompt_tokens
                if completion_tokens is not None:
                    diagnostics["completion_tokens"] = completion_tokens
                if reasoning_tokens is not None:
                    diagnostics["reasoning_tokens"] = reasoning_tokens
                if finish_reason not in {"stop", "tool_calls", "length"}:
                    raise ModelFailure("invalid_response")
                calls = []
                if finish_reason != "length":
                    for index in sorted(tool_deltas):
                        call = tool_deltas[index]
                        if call["type"] != "function" or not call["id"] or not call["name"]:
                            raise ModelFailure("invalid_response")
                        calls.append(ModelToolCall(call["id"], call["name"], call["arguments"]))
                return ModelReply(
                    "".join(content), calls, prompt_tokens or 0, completion_tokens or 0,
                    text_streamed=on_text_delta is not None,
                    truncated=finish_reason == "length",
                )
