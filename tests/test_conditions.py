from __future__ import annotations

import pytest

from orchestra.conditions.evaluator import (
    ConditionParseError,
    evaluate_condition,
    parse_condition,
)
from orchestra.models.context import Context
from orchestra.models.outcome import Outcome, OutcomeStatus


def _outcome(status: OutcomeStatus = OutcomeStatus.SUCCESS) -> Outcome:
    return Outcome(status=status)


def _context(**kwargs: str) -> Context:
    ctx = Context()
    for k, v in kwargs.items():
        ctx.set(k, v)
    return ctx


def test_parse_outcome_equals_success() -> None:
    outcome = _outcome(OutcomeStatus.SUCCESS)
    assert evaluate_condition("outcome=success", outcome, Context()) is True


def test_parse_outcome_not_equals_success() -> None:
    outcome = _outcome(OutcomeStatus.FAIL)
    assert evaluate_condition("outcome!=success", outcome, Context()) is True

    outcome_success = _outcome(OutcomeStatus.SUCCESS)
    assert evaluate_condition("outcome!=success", outcome_success, Context()) is False


def test_parse_context_key_equals_value() -> None:
    outcome = _outcome()
    context = _context(key="value")
    assert evaluate_condition("context.key=value", outcome, context) is True
    assert evaluate_condition("context.key=other", outcome, context) is False


def test_parse_conjunction() -> None:
    outcome = _outcome(OutcomeStatus.SUCCESS)
    context = _context(flag="true")
    assert evaluate_condition("outcome=success && context.flag=true", outcome, context) is True
    assert evaluate_condition("outcome=fail && context.flag=true", outcome, context) is False
    assert evaluate_condition("outcome=success && context.flag=false", outcome, context) is False


def test_missing_context_key() -> None:
    outcome = _outcome()
    context = Context()
    assert evaluate_condition("context.missing=value", outcome, context) is False
    assert evaluate_condition("context.missing!=value", outcome, context) is True


def test_empty_condition() -> None:
    outcome = _outcome()
    assert evaluate_condition("", outcome, Context()) is True
    assert evaluate_condition("   ", outcome, Context()) is True


def test_invalid_syntax() -> None:
    with pytest.raises(ConditionParseError):
        parse_condition("invalid syntax here!!!")

    with pytest.raises(ConditionParseError):
        parse_condition("outcome == success")
