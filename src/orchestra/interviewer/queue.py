from __future__ import annotations

from collections import deque

from orchestra.interviewer.models import Answer, AnswerValue, Question


class QueueInterviewer:
    def __init__(self, answers: list[Answer]) -> None:
        self._answers: deque[Answer] = deque(answers)

    def ask(self, question: Question) -> Answer:
        if self._answers:
            return self._answers.popleft()
        return Answer(value=AnswerValue.SKIPPED)

    def inform(self, message: str, stage: str = "") -> None:
        pass
