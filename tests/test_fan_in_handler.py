from __future__ import annotations

from orchestra.handlers.fan_in_handler import FanInHandler
from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


def _fan_in_node(**attrs: object) -> Node:
    return Node(id="fan_in", shape="tripleoctagon", attributes=dict(attrs))


def _graph() -> PipelineGraph:
    return PipelineGraph(name="test")


def _outcome(status: OutcomeStatus, score: float = 0.0, notes: str = "") -> Outcome:
    return Outcome(status=status, context_updates={"score": score}, notes=notes)


def test_consolidate_all_success() -> None:
    handler = FanInHandler()
    ctx = Context()
    ctx.set("parallel.results", {
        "A": _outcome(OutcomeStatus.SUCCESS, score=0.9),
        "B": _outcome(OutcomeStatus.SUCCESS, score=0.8),
    })
    result = handler.handle(_fan_in_node(), ctx, _graph())
    assert result.status == OutcomeStatus.SUCCESS
    assert result.context_updates["parallel.fan_in.best_id"] == "A"


def test_heuristic_prefers_success_over_fail() -> None:
    handler = FanInHandler()
    ctx = Context()
    ctx.set("parallel.results", {
        "A": _outcome(OutcomeStatus.FAIL, score=0.9),
        "B": _outcome(OutcomeStatus.SUCCESS, score=0.1),
    })
    result = handler.handle(_fan_in_node(), ctx, _graph())
    assert result.context_updates["parallel.fan_in.best_id"] == "B"


def test_heuristic_sorts_by_score() -> None:
    handler = FanInHandler()
    ctx = Context()
    ctx.set("parallel.results", {
        "A": _outcome(OutcomeStatus.SUCCESS, score=0.5),
        "B": _outcome(OutcomeStatus.SUCCESS, score=0.9),
    })
    result = handler.handle(_fan_in_node(), ctx, _graph())
    assert result.context_updates["parallel.fan_in.best_id"] == "B"


def test_all_failed() -> None:
    handler = FanInHandler()
    ctx = Context()
    ctx.set("parallel.results", {
        "A": _outcome(OutcomeStatus.FAIL),
        "B": _outcome(OutcomeStatus.FAIL),
    })
    result = handler.handle(_fan_in_node(), ctx, _graph())
    # wait_all is satisfied (all complete), but status is FAIL
    assert result.status == OutcomeStatus.FAIL


def test_mixed_outcomes_partial_success() -> None:
    handler = FanInHandler()
    ctx = Context()
    ctx.set("parallel.results", {
        "A": _outcome(OutcomeStatus.SUCCESS),
        "B": _outcome(OutcomeStatus.FAIL),
        "C": _outcome(OutcomeStatus.SUCCESS),
    })
    result = handler.handle(_fan_in_node(), ctx, _graph())
    assert result.status == OutcomeStatus.PARTIAL_SUCCESS


def test_context_updates_set() -> None:
    handler = FanInHandler()
    ctx = Context()
    ctx.set("parallel.results", {
        "A": _outcome(OutcomeStatus.SUCCESS, score=0.9),
    })
    result = handler.handle(_fan_in_node(), ctx, _graph())
    assert "parallel.fan_in.best_id" in result.context_updates
    assert "parallel.fan_in.best_outcome" in result.context_updates
    assert "parallel.fan_in.selected_results" in result.context_updates


def test_first_success_policy() -> None:
    handler = FanInHandler()
    ctx = Context()
    ctx.set("parallel.results", {
        "A": _outcome(OutcomeStatus.FAIL),
        "B": _outcome(OutcomeStatus.SUCCESS),
        "C": _outcome(OutcomeStatus.SUCCESS),
    })
    node = _fan_in_node(join_policy="first_success")
    result = handler.handle(node, ctx, _graph())
    assert result.status == OutcomeStatus.SUCCESS


def test_k_of_n_policy() -> None:
    handler = FanInHandler()
    ctx = Context()
    ctx.set("parallel.results", {
        "A": _outcome(OutcomeStatus.SUCCESS),
        "B": _outcome(OutcomeStatus.FAIL),
        "C": _outcome(OutcomeStatus.SUCCESS),
    })
    node = _fan_in_node(join_policy="k_of_n", k=2)
    result = handler.handle(node, ctx, _graph())
    assert result.status == OutcomeStatus.SUCCESS


def test_llm_based_selection() -> None:
    from orchestra.backends.simulation import SimulationBackend

    backend = SimulationBackend()
    handler = FanInHandler(backend=backend)
    ctx = Context()
    ctx.set("parallel.results", {
        "A": _outcome(OutcomeStatus.SUCCESS, score=0.5),
        "B": _outcome(OutcomeStatus.SUCCESS, score=0.9),
    })
    node = Node(
        id="fan_in",
        shape="tripleoctagon",
        prompt="Select the best review",
    )
    result = handler.handle(node, ctx, _graph())
    # SimulationBackend won't match branch IDs in notes, so falls back to heuristic
    assert result.context_updates["parallel.fan_in.best_id"] in ("A", "B")
