from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.interviewer.accelerator import parse_accelerator
from orchestra.interviewer.models import (
    Answer,
    AnswerValue,
    Option,
    Question,
    QuestionType,
)
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.interviewer.base import Interviewer
    from orchestra.models.context import Context
    from orchestra.models.graph import Node, PipelineGraph


class _Choice:
    __slots__ = ("key", "label", "to_node")

    def __init__(self, key: str, label: str, to_node: str) -> None:
        self.key = key
        self.label = label
        self.to_node = to_node


class WaitHumanHandler:
    def __init__(self, interviewer: Interviewer) -> None:
        self._interviewer = interviewer

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        edges = graph.get_outgoing_edges(node.id)

        choices: list[_Choice] = []
        for edge in edges:
            label = edge.label or edge.to_node
            key, clean_label = parse_accelerator(label)
            choices.append(_Choice(key=key, label=clean_label, to_node=edge.to_node))

        if not choices:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason="No outgoing edges for human gate",
            )

        options = [Option(key=c.key, label=c.label) for c in choices]
        question = Question(
            text=node.label or "Select an option:",
            type=QuestionType.MULTIPLE_CHOICE,
            options=options,
            stage=node.id,
        )

        answer = self._interviewer.ask(question)

        # Handle timeout
        if answer.value == AnswerValue.TIMEOUT:
            default_choice = node.attributes.get("human.default_choice")
            if default_choice:
                selected = self._find_choice_by_key(default_choice, choices)
                if selected is not None:
                    return self._success_outcome(selected)
            return Outcome(
                status=OutcomeStatus.RETRY,
                failure_reason="human gate timeout, no default",
            )

        # Handle skipped
        if answer.value == AnswerValue.SKIPPED:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason="human skipped interaction",
            )

        # Match answer to choice
        selected = self._find_matching_choice(answer, choices)
        if selected is None:
            selected = choices[0]

        return self._success_outcome(selected)

    def _find_matching_choice(
        self, answer: Answer, choices: list[_Choice]
    ) -> _Choice | None:
        value = str(answer.value).strip().upper()

        # Match by key
        for choice in choices:
            if choice.key.upper() == value:
                return choice

        # Match by label
        for choice in choices:
            if choice.label.strip().upper() == value:
                return choice

        # Match by selected_option key
        if answer.selected_option is not None:
            for choice in choices:
                if choice.key.upper() == answer.selected_option.key.upper():
                    return choice

        return None

    def _find_choice_by_key(
        self, key: str, choices: list[_Choice]
    ) -> _Choice | None:
        key_upper = key.strip().upper()
        for choice in choices:
            if choice.key.upper() == key_upper:
                return choice
        return None

    def _success_outcome(self, selected: _Choice) -> Outcome:
        return Outcome(
            status=OutcomeStatus.SUCCESS,
            suggested_next_ids=[selected.to_node],
            context_updates={
                "human.gate.selected": selected.key,
                "human.gate.label": selected.label,
            },
        )
