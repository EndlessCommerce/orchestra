from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OutcomeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    RETRY = "RETRY"


class Outcome(BaseModel):
    status: OutcomeStatus
    preferred_label: str = ""
    suggested_next_ids: list[str] = Field(default_factory=list)
    context_updates: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    failure_reason: str = ""
