from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from orchestra.models.outcome import Outcome, OutcomeStatus


class JoinPolicy(str, Enum):
    WAIT_ALL = "wait_all"
    FIRST_SUCCESS = "first_success"
    K_OF_N = "k_of_n"
    QUORUM = "quorum"


@dataclass
class JoinResult:
    satisfied: bool
    status: OutcomeStatus
    selected_results: list[tuple[str, Outcome]] = field(default_factory=list)
    failure_reason: str = ""


def evaluate_join(
    policy: JoinPolicy,
    results: dict[str, Outcome],
    params: dict[str, Any] | None = None,
) -> JoinResult:
    params = params or {}

    if policy == JoinPolicy.WAIT_ALL:
        return _eval_wait_all(results)
    elif policy == JoinPolicy.FIRST_SUCCESS:
        return _eval_first_success(results)
    elif policy == JoinPolicy.K_OF_N:
        return _eval_k_of_n(results, params)
    elif policy == JoinPolicy.QUORUM:
        return _eval_quorum(results, params)
    else:
        return JoinResult(
            satisfied=False,
            status=OutcomeStatus.FAIL,
            failure_reason=f"Unknown join policy: {policy}",
        )


def _eval_wait_all(results: dict[str, Outcome]) -> JoinResult:
    if not results:
        return JoinResult(
            satisfied=False,
            status=OutcomeStatus.FAIL,
            failure_reason="No branch results",
        )

    selected = list(results.items())
    statuses = {o.status for _, o in selected}

    if statuses == {OutcomeStatus.SUCCESS}:
        status = OutcomeStatus.SUCCESS
    elif statuses == {OutcomeStatus.FAIL}:
        status = OutcomeStatus.FAIL
    else:
        status = OutcomeStatus.PARTIAL_SUCCESS

    return JoinResult(satisfied=True, status=status, selected_results=selected)


def _eval_first_success(results: dict[str, Outcome]) -> JoinResult:
    for branch_id, outcome in results.items():
        if outcome.status == OutcomeStatus.SUCCESS:
            return JoinResult(
                satisfied=True,
                status=OutcomeStatus.SUCCESS,
                selected_results=[(branch_id, outcome)],
            )

    return JoinResult(
        satisfied=False,
        status=OutcomeStatus.FAIL,
        failure_reason="No successful branch found",
    )


def _eval_k_of_n(results: dict[str, Outcome], params: dict[str, Any]) -> JoinResult:
    k = int(params.get("k", 1))
    successful = [
        (bid, o) for bid, o in results.items()
        if o.status in (OutcomeStatus.SUCCESS, OutcomeStatus.PARTIAL_SUCCESS)
    ]

    if len(successful) >= k:
        return JoinResult(
            satisfied=True,
            status=OutcomeStatus.SUCCESS,
            selected_results=successful,
        )

    return JoinResult(
        satisfied=False,
        status=OutcomeStatus.FAIL,
        failure_reason=f"Only {len(successful)} of {k} required branches succeeded",
    )


def _eval_quorum(results: dict[str, Outcome], params: dict[str, Any]) -> JoinResult:
    quorum_percent = float(params.get("quorum_percent", 50))
    total = len(results)
    if total == 0:
        return JoinResult(
            satisfied=False,
            status=OutcomeStatus.FAIL,
            failure_reason="No branch results",
        )

    successful = [
        (bid, o) for bid, o in results.items()
        if o.status in (OutcomeStatus.SUCCESS, OutcomeStatus.PARTIAL_SUCCESS)
    ]
    fraction = (len(successful) / total) * 100

    if fraction >= quorum_percent:
        return JoinResult(
            satisfied=True,
            status=OutcomeStatus.SUCCESS,
            selected_results=successful,
        )

    return JoinResult(
        satisfied=False,
        status=OutcomeStatus.FAIL,
        failure_reason=f"Quorum not met: {fraction:.0f}% < {quorum_percent}%",
    )
