"""Public agent-runtime contracts, independent of learner state and storage."""

from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from .models import Contract


class RuntimeContract(Contract):
    model_config = ConfigDict(extra="forbid", strict=True)


class Choice(RuntimeContract):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=300)

    @field_validator("id", "text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank.")
        return value


class MultipleChoiceInput(RuntimeContract):
    question: str = Field(min_length=1, max_length=1000)
    choices: list[Choice] = Field(min_length=3, max_length=5)
    presentation: Literal["after_response", "inline"] = Field(
        default="after_response",
        description=(
            "Use after_response for follow-up choices that depend on the explanation: "
            "display them after the response completes successfully. Use inline for a "
            "clarification or standalone question: display it at the tool's position."
        ),
    )

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank.")
        return value

    @model_validator(mode="after")
    def unique_choices(self):
        if len({choice.id for choice in self.choices}) != len(self.choices):
            raise ValueError("Choice IDs must be unique.")
        return self


class MultipleChoiceElement(MultipleChoiceInput):
    type: Literal["multiple_choice"] = "multiple_choice"
    element_id: str = Field(min_length=1, max_length=100)


class MultipleChoiceOutput(RuntimeContract):
    element: MultipleChoiceElement


class RuntimeRequest(RuntimeContract):
    session_id: str = Field(min_length=1, max_length=100)
    session_epoch: int = Field(default=0, ge=0)
    request_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank.")
        return value


class RuntimeControl(RuntimeContract):
    session_id: str = Field(min_length=1, max_length=100)
    session_epoch: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class RuntimeReset(RuntimeContract):
    session_id: str = Field(min_length=1, max_length=100)
    session_epoch: int = Field(ge=0)


class RuntimeResetResult(RuntimeContract):
    session_id: str
    session_epoch: int


class RuntimeCancelResult(RuntimeContract):
    run_id: str
    status: Literal["running", "completed", "failed", "cancelled"]


class RunLimits(RuntimeContract):
    model_calls: int = Field(default=4, ge=2, le=10)
    tool_calls: int = Field(default=4, ge=1, le=10)
    total_calls: int = Field(default=8, ge=2, le=20)
    result_chars: int = Field(default=6000, ge=256, le=16000)
    max_failures: int = Field(default=2, ge=1, le=5)


class RunUsage(RuntimeContract):
    model_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: int = 0


class RunOutcome(RuntimeContract):
    run_id: str
    request_id: str
    session_epoch: int
    status: Literal["completed", "failed", "cancelled"]
    text: str
    elements: list[MultipleChoiceElement] = Field(default_factory=list)
    reason: str | None = None
    notice: str | None = None
    usage: RunUsage


class RunEvent(RuntimeContract):
    run_id: str
    request_id: str
    session_epoch: int
    sequence: int
    type: Literal["progress", "message_delta", "element", "outcome"]
    call_id: str | None = None
    message: str | None = None
    element: MultipleChoiceElement | None = None
    outcome: RunOutcome | None = None
