from orchestra.interviewer.auto_approve import AutoApproveInterviewer
from orchestra.interviewer.callback import CallbackInterviewer
from orchestra.interviewer.models import (
    Answer,
    AnswerValue,
    Option,
    Question,
    QuestionType,
)
from orchestra.interviewer.queue import QueueInterviewer
from orchestra.interviewer.recording import RecordingInterviewer


class TestAutoApproveInterviewer:
    def test_yes_no_returns_yes(self):
        interviewer = AutoApproveInterviewer()
        q = Question(text="Proceed?", type=QuestionType.YES_NO)
        answer = interviewer.ask(q)
        assert answer.value == AnswerValue.YES

    def test_confirmation_returns_yes(self):
        interviewer = AutoApproveInterviewer()
        q = Question(text="Confirm?", type=QuestionType.CONFIRMATION)
        answer = interviewer.ask(q)
        assert answer.value == AnswerValue.YES

    def test_multiple_choice_returns_first_option(self):
        interviewer = AutoApproveInterviewer()
        options = [
            Option(key="A", label="Approve"),
            Option(key="R", label="Reject"),
        ]
        q = Question(text="Select:", type=QuestionType.MULTIPLE_CHOICE, options=options)
        answer = interviewer.ask(q)
        assert answer.value == "A"
        assert answer.selected_option == options[0]

    def test_freeform_returns_auto_approved(self):
        interviewer = AutoApproveInterviewer()
        q = Question(text="Enter text:", type=QuestionType.FREEFORM)
        answer = interviewer.ask(q)
        assert answer.value == "auto-approved"
        assert answer.text == "auto-approved"


class TestQueueInterviewer:
    def test_single_answer_dequeue(self):
        answers = [Answer(value=AnswerValue.YES)]
        interviewer = QueueInterviewer(answers)
        q = Question(text="Proceed?", type=QuestionType.YES_NO)
        answer = interviewer.ask(q)
        assert answer.value == AnswerValue.YES

    def test_multiple_answers_in_sequence(self):
        answers = [
            Answer(value=AnswerValue.YES),
            Answer(value=AnswerValue.NO),
            Answer(text="hello", value="hello"),
        ]
        interviewer = QueueInterviewer(answers)
        q = Question(text="Q", type=QuestionType.YES_NO)

        assert interviewer.ask(q).value == AnswerValue.YES
        assert interviewer.ask(q).value == AnswerValue.NO
        assert interviewer.ask(q).text == "hello"

    def test_exhausted_returns_skipped(self):
        interviewer = QueueInterviewer([Answer(value=AnswerValue.YES)])
        q = Question(text="Q", type=QuestionType.YES_NO)
        interviewer.ask(q)  # consume the one answer
        answer = interviewer.ask(q)
        assert answer.value == AnswerValue.SKIPPED


class TestRecordingInterviewer:
    def test_wraps_inner_and_records(self):
        inner = AutoApproveInterviewer()
        recorder = RecordingInterviewer(inner)
        q = Question(text="Proceed?", type=QuestionType.YES_NO)

        answer = recorder.ask(q)
        assert answer.value == AnswerValue.YES
        assert len(recorder.recordings) == 1
        assert recorder.recordings[0] == (q, answer)

    def test_recordings_accessible_after_multiple_asks(self):
        inner = QueueInterviewer([
            Answer(value=AnswerValue.YES),
            Answer(value=AnswerValue.NO),
        ])
        recorder = RecordingInterviewer(inner)

        q1 = Question(text="Q1", type=QuestionType.YES_NO)
        q2 = Question(text="Q2", type=QuestionType.YES_NO)
        recorder.ask(q1)
        recorder.ask(q2)

        assert len(recorder.recordings) == 2
        assert recorder.recordings[0][0].text == "Q1"
        assert recorder.recordings[1][0].text == "Q2"


class TestCallbackInterviewer:
    def test_delegates_to_callback(self):
        def my_callback(question: Question) -> Answer:
            return Answer(text=f"answer to {question.text}", value="custom")

        interviewer = CallbackInterviewer(my_callback)
        q = Question(text="What?", type=QuestionType.FREEFORM)
        answer = interviewer.ask(q)
        assert answer.text == "answer to What?"
        assert answer.value == "custom"
