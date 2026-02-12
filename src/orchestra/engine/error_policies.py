from __future__ import annotations

from enum import Enum


class ErrorPolicy(str, Enum):
    FAIL_FAST = "fail_fast"
    CONTINUE = "continue"
    IGNORE = "ignore"
