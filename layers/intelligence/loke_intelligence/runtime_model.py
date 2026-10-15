"""Server-side runtime adapters. Demo is deterministic; live uses OpenRouter."""

import asyncio
import json
import os
import re
import time

import httpx

from .agent_runtime import ModelReply, ModelToolCall
from .runtime_errors import ModelFailure


class DemoRuntimeModel:
    async def complete(self, messages, tools, *, tools_enabled, output_chars):
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

    async def complete(self, messages, tools, *, tools_enabled, output_chars):
        started = time.monotonic()
        diagnostics = {
            "model": os.getenv("TEXT_MODEL", "openai/gpt-4.1-mini"),
            "provider": os.getenv("OPENROUTER_PROVIDER", "OpenAI"),
            "tools_enabled": tools_enabled, "max_tokens": min(1500, output_chars),
            "require_parameters": True, "data_collection": "deny", "retry_count": 0,
        }
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        # These are configuration identifiers, never free-form provider diagnostics.
        for name in ("model", "provider"):
            value = diagnostics[name]
            if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", value) or (key and key in value):
                diagnostics[name] = "[omitted]"
        try:
            return await self._complete(messages, tools, tools_enabled=tools_enabled,
                                        output_chars=output_chars, diagnostics=diagnostics)
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

    async def _complete(self, messages, tools, *, tools_enabled, output_chars, diagnostics):
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ModelFailure("configuration")
        payload = {
            "model": os.getenv("TEXT_MODEL", "openai/gpt-4.1-mini"),
            "messages": messages, "tools": tools,
            "tool_choice": "auto" if tools_enabled else "none",
            "max_tokens": min(1500, output_chars), "stream": False,
            "provider": {"require_parameters": True, "data_collection": "deny",
                         "only": [os.getenv("OPENROUTER_PROVIDER", "OpenAI")]},
        }
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            async with client.stream(
                "POST", "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"}, json=payload,
            ) as response:
                diagnostics["http_status"] = response.status_code
                request_id = response.headers.get("x-request-id", "")
                if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) and key not in request_id:
                    diagnostics["provider_request_id"] = request_id
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 64000:
                        raise ModelFailure("response_size")
                if not response.is_success:
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
        data = json.loads(body)
        choice = data["choices"][0]
        if choice.get("finish_reason") not in {"stop", "tool_calls"}:
            raise ModelFailure("invalid_response")
        message = choice["message"]
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ModelFailure("invalid_response")
        calls = []
        for call in message.get("tool_calls") or []:
            function = call["function"]
            if call.get("type") != "function" or not all(isinstance(value, str) for value in (
                call["id"], function["name"], function["arguments"],
            )):
                raise ModelFailure("invalid_response")
            calls.append(ModelToolCall(call["id"], function["name"], function["arguments"]))
        usage = data.get("usage") or {}
        return ModelReply(content, calls, int(usage.get("prompt_tokens", 0)),
                          int(usage.get("completion_tokens", 0)))
