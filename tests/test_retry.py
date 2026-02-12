from __future__ import annotations

import random

from orchestra.engine.retry import (
    BackoffConfig,
    RetryPolicy,
    calculate_delay,
    execute_with_retry,
)
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus


def _node(node_id: str = "test_node", **attrs: object) -> Node:
    return Node(id=node_id, shape="box", attributes=dict(attrs))


def _graph() -> PipelineGraph:
    return PipelineGraph(name="test")


def _noop_sleep(_delay: float) -> None:
    pass


def test_retry_on_fail() -> None:
    handler = SimulationCodergenHandler(
        outcome_sequences={"work": [OutcomeStatus.FAIL, OutcomeStatus.FAIL, OutcomeStatus.SUCCESS]}
    )
    node = _node("work", max_retries=2)
    policy = RetryPolicy(max_attempts=3, backoff=BackoffConfig(jitter=False))

    outcome = execute_with_retry(
        node=node, handler=handler, context=Context(), graph=_graph(),
        policy=policy, sleep_fn=_noop_sleep,
    )
    assert outcome.status == OutcomeStatus.SUCCESS


def test_retry_on_retry_status() -> None:
    handler = SimulationCodergenHandler(
        outcome_sequences={"work": [OutcomeStatus.RETRY, OutcomeStatus.SUCCESS]}
    )
    node = _node("work", max_retries=1)
    policy = RetryPolicy(max_attempts=2, backoff=BackoffConfig(jitter=False))

    outcome = execute_with_retry(
        node=node, handler=handler, context=Context(), graph=_graph(),
        policy=policy, sleep_fn=_noop_sleep,
    )
    assert outcome.status == OutcomeStatus.SUCCESS


def test_retry_exhaustion() -> None:
    handler = SimulationCodergenHandler(
        outcome_sequences={"work": [OutcomeStatus.FAIL, OutcomeStatus.FAIL, OutcomeStatus.FAIL]}
    )
    node = _node("work")
    policy = RetryPolicy(max_attempts=3, backoff=BackoffConfig(jitter=False))

    outcome = execute_with_retry(
        node=node, handler=handler, context=Context(), graph=_graph(),
        policy=policy, sleep_fn=_noop_sleep,
    )
    assert outcome.status == OutcomeStatus.FAIL


def test_backoff_delays() -> None:
    rng = random.Random(42)
    config = BackoffConfig(initial_delay_ms=200, backoff_factor=2.0, jitter=False)

    d1 = calculate_delay(config, attempt=1, rng=rng)
    d2 = calculate_delay(config, attempt=2, rng=rng)
    d3 = calculate_delay(config, attempt=3, rng=rng)

    assert d1 == 200.0
    assert d2 == 400.0
    assert d3 == 800.0


def test_backoff_delays_with_jitter() -> None:
    rng = random.Random(42)
    config = BackoffConfig(initial_delay_ms=200, backoff_factor=2.0, jitter=True)

    d1 = calculate_delay(config, attempt=1, rng=rng)
    assert 100.0 <= d1 <= 300.0


def test_allow_partial() -> None:
    handler = SimulationCodergenHandler(
        outcome_sequences={"work": [OutcomeStatus.RETRY, OutcomeStatus.RETRY]}
    )
    node = _node("work", allow_partial=True)
    policy = RetryPolicy(max_attempts=2, backoff=BackoffConfig(jitter=False))

    outcome = execute_with_retry(
        node=node, handler=handler, context=Context(), graph=_graph(),
        policy=policy, sleep_fn=_noop_sleep,
    )
    assert outcome.status == OutcomeStatus.PARTIAL_SUCCESS


def test_no_retry_on_success() -> None:
    call_count = 0
    original_handler = SimulationCodergenHandler()

    class CountingHandler:
        def handle(self, node, context, graph):
            nonlocal call_count
            call_count += 1
            return original_handler.handle(node, context, graph)

    node = _node("work")
    policy = RetryPolicy(max_attempts=3, backoff=BackoffConfig(jitter=False))

    outcome = execute_with_retry(
        node=node, handler=CountingHandler(), context=Context(), graph=_graph(),
        policy=policy, sleep_fn=_noop_sleep,
    )
    assert outcome.status == OutcomeStatus.SUCCESS
    assert call_count == 1
