"""Ephemeral focused conversations. These contracts never become learner evidence."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .runtime import RuntimeContract


class SideThreadTurn(RuntimeContract):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=24000)


class SideThreadAnchor(RuntimeContract):
    chat_id: str = Field(min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=100)
    source_markdown: str = Field(min_length=1, max_length=100000)
    selected_text: str = Field(min_length=1, max_length=20000)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    stream_version: Literal["loke-rendered-v1"]

    @model_validator(mode="after")
    def valid_offsets(self):
        # Offsets identify the rendered anchor. Never apply them to source_markdown.
        if self.end_offset <= self.start_offset:
            raise ValueError("The source range must not be empty.")
        return self


class SideThreadRequest(RuntimeContract):
    generation_id: str = Field(min_length=1, max_length=100)
    thread_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)
    anchor: SideThreadAnchor
    main_history: list[SideThreadTurn] = Field(default_factory=list, max_length=200)
    history: list[SideThreadTurn] = Field(default_factory=list, max_length=100)
    main_history_truncated: bool = False
    history_truncated: bool = False
    question: str = Field(min_length=1, max_length=8000)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("The question must not be blank.")
        return value

    @model_validator(mode="after")
    def bounded_input(self):
        if sum(len(turn.text) for turn in self.main_history + self.history) > 200000:
            raise ValueError("Conversation context exceeds its limit.")
        return self


class SideThreadEvent(RuntimeContract):
    thread_id: str
    request_id: str
    type: Literal["delta", "completed", "error"]
    text: str = ""
