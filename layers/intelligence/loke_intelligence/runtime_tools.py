"""Registration, permission and schema validation for runtime tools."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from loke_contracts.runtime import MultipleChoiceElement, MultipleChoiceInput, MultipleChoiceOutput
from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class ToolContext:
    run_id: str
    call_id: str
    session_id: str


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    handler: Callable[[BaseModel, ToolContext], Awaitable[Any]]
    permission: Callable[[ToolContext], bool]
    public_elements: Callable[[BaseModel], list[MultipleChoiceElement]] | None = None
    timeout_seconds: float = 3.0
    result_chars: int = 6000


@dataclass
class ToolResult:
    call_id: str
    data: dict | None = None
    error: dict | None = None
    elements: list[MultipleChoiceElement] | None = None

    def observation(self):
        return {"result": self.data} if self.error is None else {"error": self.error}


async def bounded_call(awaitable, timeout: float | None = None):
    """Respect cancellation and optional timeouts even if an adapter finishes late."""
    task = asyncio.create_task(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            raise TimeoutError
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            # Retrieve a late exception without allowing a late result to publish.
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]):
        self.specs = {spec.name: spec for spec in specs}
        if len(self.specs) != len(specs):
            raise ValueError("Duplicate tool registration.")
        for spec in specs:
            if spec.timeout_seconds <= 0 or spec.result_chars < 256:
                raise ValueError("Invalid tool limits.")
            for schema in (spec.input_schema, spec.output_schema):
                if schema.model_config.get("extra") != "forbid":
                    raise ValueError("Tool schemas must forbid extra fields.")

    def declarations(self):
        declarations = []
        for spec in self.specs.values():
            parameters = spec.input_schema.model_json_schema()
            # Strict tool schemas require defaulted fields too; local validation keeps defaults.
            parameters["required"] = list(parameters["properties"])
            declarations.append({"type": "function", "function": {
                "name": spec.name, "description": spec.description,
                "strict": True, "parameters": parameters,
            }})
        return declarations

    async def execute(self, name, arguments, context: ToolContext, result_chars: int):
        def error(code, message):
            return ToolResult(context.call_id, error={"code": code, "message": message})

        spec = self.specs.get(name)
        if spec is None:
            return error("unknown_tool", "Use a registered tool name.")
        try:
            if not spec.permission(context):
                return error("permission_denied", "This tool is unavailable in this session.")
            try:
                payload = spec.input_schema.model_validate_json(arguments, strict=True)
            except ValidationError:
                return error("invalid_arguments", "Arguments do not match the tool input schema.")
            result = await bounded_call(spec.handler(payload, context), spec.timeout_seconds)
            try:
                result = spec.output_schema.model_validate(
                    result.model_dump() if isinstance(result, BaseModel) else result, strict=True
                )
                elements = [MultipleChoiceElement.model_validate(
                    element.model_dump() if isinstance(element, BaseModel) else element, strict=True
                )
                            for element in (spec.public_elements(result) if spec.public_elements else [])]
            except (ValidationError, TypeError, ValueError):
                return error("invalid_result", "Tool output does not match the output schema.")
            if len(result.model_dump_json()) > min(result_chars, spec.result_chars):
                return error("result_too_large", "Tool output exceeds its result budget.")
            return ToolResult(context.call_id, data=result.model_dump(mode="json"), elements=elements)
        except TimeoutError:
            return error("tool_timeout", "Tool execution exceeded its deadline.")
        except Exception:
            return error("handler_error", "Tool execution failed.")


async def multiple_choice(payload: MultipleChoiceInput, context: ToolContext):
    return MultipleChoiceOutput(element=MultipleChoiceElement(
        **payload.model_dump(),
        element_id=str(uuid5(NAMESPACE_URL, f"{context.run_id}/{context.call_id}")),
    ))


def example_registry():
    return ToolRegistry([ToolSpec(
        name="generate_multiple_choice_response",
        description=(
            "Display a question with 3–5 choices you author at this point in the response. "
            "Write any explanation the question depends on before calling this tool."
        ),
        input_schema=MultipleChoiceInput,
        output_schema=MultipleChoiceOutput,
        handler=multiple_choice,
        permission=lambda context: True,
        public_elements=lambda result: [result.element],
    )])
