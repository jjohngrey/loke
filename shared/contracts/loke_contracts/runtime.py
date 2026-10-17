"""Public agent-runtime contracts, independent of learner state and storage."""

from typing import Annotated, Literal

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


class TextBlock(RuntimeContract):
    kind: Literal["text"]
    block_id: str
    state: Literal["streaming", "complete", "failed", "cancelled"]
    text: str


class ToolBlock(RuntimeContract):
    kind: Literal["tool"]
    block_id: str
    call_id: str
    state: Literal["pending", "ready", "failed", "cancelled"]
    elements: list[MultipleChoiceElement]
    notice: str | None = None


OutputBlock = Annotated[TextBlock | ToolBlock, Field(discriminator="kind")]


class RunOutcome(RuntimeContract):
    run_id: str
    request_id: str
    session_epoch: int
    status: Literal["completed", "failed", "cancelled"]
    blocks: list[OutputBlock]
    text: str
    elements: list[MultipleChoiceElement] = Field(default_factory=list)
    reason: str | None = None
    notice: str | None = None
    usage: RunUsage

    @model_validator(mode="after")
    def terminal_blocks(self):
        ids = [block.block_id for block in self.blocks]
        if len(set(ids)) != len(ids):
            raise ValueError("Block IDs must be unique.")
        if any(block.state in {"streaming", "pending"} for block in self.blocks):
            raise ValueError("An outcome cannot contain unfinished blocks.")
        return self


class RunEvent(RuntimeContract):
    run_id: str
    request_id: str
    session_epoch: int
    sequence: int
    type: Literal["progress", "block_start", "text_delta", "block_end", "tool_result", "outcome"]
    call_id: str | None = None
    block_id: str | None = None
    message: str | None = None
    block: OutputBlock | None = None
    outcome: RunOutcome | None = None

    @model_validator(mode="after")
    def block_event(self):
        if self.type == "text_delta" and (not self.block_id or self.message is None):
            raise ValueError("Text deltas require a block ID and text.")
        if self.type == "block_start":
            if self.block is None or self.block.state not in {"streaming", "pending"}:
                raise ValueError("Block starts require an unfinished block.")
        if self.type == "block_end":
            if not isinstance(self.block, TextBlock) or self.block.state == "streaming":
                raise ValueError("Block ends require a settled text block.")
        if self.type == "tool_result":
            if not isinstance(self.block, ToolBlock) or self.block.state == "pending":
                raise ValueError("Tool results require a settled tool block.")
        return self
