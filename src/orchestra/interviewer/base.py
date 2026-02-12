from __future__ import annotations

from typing import Protocol, runtime_checkable

from orchestra.interviewer.models import Answer, Question


@runtime_checkable
class Interviewer(Protocol):
    def ask(self, question: Question) -> Answer: ...

    def ask_multiple(self, questions: list[Question]) -> list[Answer]:
        return [self.ask(q) for q in questions]

    def inform(self, message: str, stage: str = "") -> None: ...
