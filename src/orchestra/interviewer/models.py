from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    YES_NO = "YES_NO"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    FREEFORM = "FREEFORM"
    CONFIRMATION = "CONFIRMATION"


class AnswerValue(str, Enum):
    YES = "YES"
    NO = "NO"
    SKIPPED = "SKIPPED"
    TIMEOUT = "TIMEOUT"


class Option(BaseModel):
    key: str
    label: str


class Answer(BaseModel):
    value: str | AnswerValue = ""
    selected_option: Option | None = None
    text: str = ""


class Question(BaseModel):
    text: str
    type: QuestionType
    options: list[Option] = Field(default_factory=list)
    stage: str = ""
    timeout_seconds: float | None = None
    default: Answer | None = None
