from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.interviewer.models import Answer, Question

if TYPE_CHECKING:
    from orchestra.interviewer.base import Interviewer


class RecordingInterviewer:
    def __init__(self, inner: Interviewer) -> None:
        self._inner = inner
        self._recordings: list[tuple[Question, Answer]] = []

    def ask(self, question: Question) -> Answer:
        answer = self._inner.ask(question)
        self._recordings.append((question, answer))
        return answer

    @property
    def recordings(self) -> list[tuple[Question, Answer]]:
        return list(self._recordings)

    def inform(self, message: str, stage: str = "") -> None:
        self._inner.inform(message, stage)
