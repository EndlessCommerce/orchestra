from __future__ import annotations

from orchestra.engine.join_policies import JoinPolicy, evaluate_join
from orchestra.models.outcome import Outcome, OutcomeStatus


def _outcome(status: OutcomeStatus, score: float = 0.0) -> Outcome:
    return Outcome(status=status, context_updates={"score": score})


def test_wait_all_all_success() -> None:
    results = {
        "A": _outcome(OutcomeStatus.SUCCESS),
        "B": _outcome(OutcomeStatus.SUCCESS),
    }
    jr = evaluate_join(JoinPolicy.WAIT_ALL, results)
    assert jr.satisfied is True
    assert jr.status == OutcomeStatus.SUCCESS
    assert len(jr.selected_results) == 2


def test_wait_all_all_fail() -> None:
    results = {
        "A": _outcome(OutcomeStatus.FAIL),
        "B": _outcome(OutcomeStatus.FAIL),
    }
    jr = evaluate_join(JoinPolicy.WAIT_ALL, results)
    assert jr.satisfied is True
    assert jr.status == OutcomeStatus.FAIL


def test_wait_all_mixed() -> None:
    results = {
        "A": _outcome(OutcomeStatus.SUCCESS),
        "B": _outcome(OutcomeStatus.FAIL),
    }
    jr = evaluate_join(JoinPolicy.WAIT_ALL, results)
    assert jr.satisfied is True
    assert jr.status == OutcomeStatus.PARTIAL_SUCCESS


def test_first_success_found() -> None:
    results = {
        "A": _outcome(OutcomeStatus.FAIL),
        "B": _outcome(OutcomeStatus.SUCCESS),
    }
    jr = evaluate_join(JoinPolicy.FIRST_SUCCESS, results)
    assert jr.satisfied is True
    assert jr.status == OutcomeStatus.SUCCESS
    assert len(jr.selected_results) == 1
    assert jr.selected_results[0][0] == "B"


def test_first_success_none() -> None:
    results = {
        "A": _outcome(OutcomeStatus.FAIL),
        "B": _outcome(OutcomeStatus.FAIL),
    }
    jr = evaluate_join(JoinPolicy.FIRST_SUCCESS, results)
    assert jr.satisfied is False
    assert jr.status == OutcomeStatus.FAIL


def test_k_of_n_satisfied() -> None:
    results = {
        "A": _outcome(OutcomeStatus.SUCCESS),
        "B": _outcome(OutcomeStatus.FAIL),
        "C": _outcome(OutcomeStatus.SUCCESS),
    }
    jr = evaluate_join(JoinPolicy.K_OF_N, results, {"k": 2})
    assert jr.satisfied is True
    assert jr.status == OutcomeStatus.SUCCESS


def test_k_of_n_not_satisfied() -> None:
    results = {
        "A": _outcome(OutcomeStatus.SUCCESS),
        "B": _outcome(OutcomeStatus.FAIL),
        "C": _outcome(OutcomeStatus.FAIL),
    }
    jr = evaluate_join(JoinPolicy.K_OF_N, results, {"k": 2})
    assert jr.satisfied is False


def test_quorum_satisfied() -> None:
    results = {
        "A": _outcome(OutcomeStatus.SUCCESS),
        "B": _outcome(OutcomeStatus.SUCCESS),
        "C": _outcome(OutcomeStatus.FAIL),
        "D": _outcome(OutcomeStatus.FAIL),
    }
    jr = evaluate_join(JoinPolicy.QUORUM, results, {"quorum_percent": 50})
    assert jr.satisfied is True


def test_quorum_not_satisfied() -> None:
    results = {
        "A": _outcome(OutcomeStatus.SUCCESS),
        "B": _outcome(OutcomeStatus.FAIL),
        "C": _outcome(OutcomeStatus.FAIL),
        "D": _outcome(OutcomeStatus.FAIL),
    }
    jr = evaluate_join(JoinPolicy.QUORUM, results, {"quorum_percent": 50})
    assert jr.satisfied is False


def test_wait_all_empty() -> None:
    jr = evaluate_join(JoinPolicy.WAIT_ALL, {})
    assert jr.satisfied is False
    assert jr.status == OutcomeStatus.FAIL
