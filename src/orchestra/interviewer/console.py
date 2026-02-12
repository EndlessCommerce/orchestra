from __future__ import annotations

import threading

from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.key_binding import KeyBindings

from orchestra.interviewer.models import Answer, AnswerValue, Option, Question, QuestionType


class ConsoleInterviewer:
    def __init__(self, *, multiline: bool = True) -> None:
        self._multiline = multiline

    def ask(self, question: Question) -> Answer:
        if question.type == QuestionType.MULTIPLE_CHOICE:
            return self._ask_multiple_choice(question)
        if question.type == QuestionType.YES_NO:
            return self._ask_yes_no(question)
        if question.type == QuestionType.CONFIRMATION:
            return self._ask_confirmation(question)
        return self._ask_freeform(question)

    def inform(self, message: str, stage: str = "") -> None:
        prefix = f"[{stage}] " if stage else ""
        print(f"[i] {prefix}{message}", flush=True)

    def _ask_multiple_choice(self, question: Question) -> Answer:
        print(f"[?] {question.text}", flush=True)
        for option in question.options:
            print(f"  [{option.key}] {option.label}", flush=True)

        response = self._read_input("Select: ", question.timeout_seconds)
        if response is None:
            return self._handle_timeout(question)

        response = response.strip().upper()
        matched = self._find_option(response, question.options)
        if matched is not None:
            return Answer(value=matched.key, selected_option=matched)

        # Fallback to first option
        if question.options:
            first = question.options[0]
            return Answer(value=first.key, selected_option=first)
        return Answer(value=AnswerValue.SKIPPED)

    def _ask_yes_no(self, question: Question) -> Answer:
        return self._ask_binary(question)

    def _ask_confirmation(self, question: Question) -> Answer:
        return self._ask_binary(question)

    def _ask_binary(self, question: Question) -> Answer:
        print(f"[?] {question.text}", flush=True)
        response = self._read_input("[Y/N]: ", question.timeout_seconds)
        if response is None:
            return self._handle_timeout(question)

        response = response.strip().upper()
        if response in ("Y", "YES"):
            return Answer(value=AnswerValue.YES)
        return Answer(value=AnswerValue.NO)

    def _ask_freeform(self, question: Question) -> Answer:
        print(f"[?] {question.text}", flush=True)
        if self._multiline:
            print("(Alt+Enter to submit)", flush=True)
        try:
            if question.timeout_seconds is not None:
                response = self._read_input("> ", question.timeout_seconds)
                if response is None:
                    return self._handle_timeout(question)
            else:
                response = self._prompt_freeform()
        except (EOFError, KeyboardInterrupt):
            return self._handle_timeout(question)
        return Answer(text=response.strip(), value=response.strip())

    def _prompt_freeform(self) -> str:
        if self._multiline:
            bindings = KeyBindings()

            @bindings.add("enter")
            def _newline(event: object) -> None:
                event.current_buffer.insert_text("\n")  # type: ignore[union-attr]

            @bindings.add("escape", "enter")
            def _submit(event: object) -> None:
                event.current_buffer.validate_and_handle()  # type: ignore[union-attr]

            return pt_prompt("> ", multiline=True, key_bindings=bindings)
        return pt_prompt("> ")

    def _find_option(self, response: str, options: list[Option]) -> Option | None:
        for option in options:
            if response == option.key.upper():
                return option
        for option in options:
            if response == option.label.upper():
                return option
        return None

    def _handle_timeout(self, question: Question) -> Answer:
        if question.default is not None:
            return question.default
        return Answer(value=AnswerValue.TIMEOUT)

    def _read_input(self, prompt: str, timeout: float | None) -> str | None:
        if timeout is None:
            try:
                return input(prompt)
            except (EOFError, KeyboardInterrupt):
                return None

        result: list[str] = []
        event = threading.Event()

        def _reader() -> None:
            try:
                result.append(input(prompt))
            except (EOFError, KeyboardInterrupt):
                pass
            finally:
                event.set()

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()

        if event.wait(timeout=timeout):
            return result[0] if result else None
        return None
