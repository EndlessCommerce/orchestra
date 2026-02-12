from __future__ import annotations

from typing import Callable

from orchestra.interviewer.models import Answer, Question


class CallbackInterviewer:
    def __init__(self, callback: Callable[[Question], Answer]) -> None:
        self._callback = callback

    def ask(self, question: Question) -> Answer:
        return self._callback(question)

    def inform(self, message: str, stage: str = "") -> None:
        pass
