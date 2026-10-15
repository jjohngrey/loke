"""Server-side runtime adapters. Demo is deterministic; live uses OpenRouter."""

import asyncio
import json
import os

import httpx

from .agent_runtime import ModelReply, ModelToolCall


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
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ValueError("Runtime model access requires OPENROUTER_API_KEY.")
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
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 64000:
                        raise ValueError("Model response exceeds the transport limit.")
                if not response.is_success:
                    # Keep the bounded body readable after the transport stream closes.
                    httpx.Response(
                        response.status_code, content=bytes(body), request=response.request,
                    ).raise_for_status()
        data = json.loads(body)
        choice = data["choices"][0]
        if choice.get("finish_reason") not in {"stop", "tool_calls"}:
            raise ValueError("Model response was incomplete.")
        message = choice["message"]
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ValueError("Model content must be text.")
        calls = []
        for call in message.get("tool_calls") or []:
            function = call["function"]
            if call.get("type") != "function" or not all(isinstance(value, str) for value in (
                call["id"], function["name"], function["arguments"],
            )):
                raise ValueError("Malformed model tool call.")
            calls.append(ModelToolCall(call["id"], function["name"], function["arguments"]))
        usage = data.get("usage") or {}
        return ModelReply(content, calls, int(usage.get("prompt_tokens", 0)),
                          int(usage.get("completion_tokens", 0)))
