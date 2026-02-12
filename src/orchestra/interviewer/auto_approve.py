from __future__ import annotations

from orchestra.interviewer.models import Answer, AnswerValue, Question, QuestionType


class AutoApproveInterviewer:
    def ask(self, question: Question) -> Answer:
        if question.type in (QuestionType.YES_NO, QuestionType.CONFIRMATION):
            return Answer(value=AnswerValue.YES)
        if question.type == QuestionType.MULTIPLE_CHOICE and question.options:
            return Answer(
                value=question.options[0].key,
                selected_option=question.options[0],
            )
        return Answer(value="auto-approved", text="auto-approved")

    def inform(self, message: str, stage: str = "") -> None:
        pass
