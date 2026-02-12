from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.handlers.base import NodeHandler


class EventEmitter(Protocol):
    def emit(self, event_type: str, **data: Any) -> None: ...


@dataclass
class BackoffConfig:
    initial_delay_ms: int = 200
    backoff_factor: float = 2.0
    max_delay_ms: int = 60000
    jitter: bool = True


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    backoff: BackoffConfig = field(default_factory=BackoffConfig)


PRESET_POLICIES: dict[str, RetryPolicy] = {
    "none": RetryPolicy(max_attempts=1),
    "standard": RetryPolicy(
        max_attempts=5,
        backoff=BackoffConfig(initial_delay_ms=200, backoff_factor=2.0),
    ),
    "aggressive": RetryPolicy(
        max_attempts=5,
        backoff=BackoffConfig(initial_delay_ms=500, backoff_factor=2.0),
    ),
    "linear": RetryPolicy(
        max_attempts=3,
        backoff=BackoffConfig(initial_delay_ms=500, backoff_factor=1.0),
    ),
    "patient": RetryPolicy(
        max_attempts=3,
        backoff=BackoffConfig(initial_delay_ms=2000, backoff_factor=3.0),
    ),
}


def calculate_delay(config: BackoffConfig, attempt: int, rng: random.Random | None = None) -> float:
    delay = config.initial_delay_ms * (config.backoff_factor ** (attempt - 1))
    delay = min(delay, config.max_delay_ms)
    if config.jitter:
        r = rng if rng is not None else random.Random()
        delay = delay * r.uniform(0.5, 1.5)
    return delay


def build_retry_policy(node: Node, graph: PipelineGraph) -> RetryPolicy:
    max_retries = node.attributes.get("max_retries")
    if max_retries is None:
        max_retries = graph.graph_attributes.get("default_max_retry", 0)
    max_retries = int(max_retries)

    backoff_name = node.attributes.get("backoff_policy", "standard")
    preset = PRESET_POLICIES.get(backoff_name, PRESET_POLICIES["standard"])

    return RetryPolicy(
        max_attempts=max_retries + 1,
        backoff=preset.backoff,
    )


def execute_with_retry(
    node: Node,
    handler: NodeHandler,
    context: Context,
    graph: PipelineGraph,
    policy: RetryPolicy,
    emitter: EventEmitter | None = None,
    rng: random.Random | None = None,
    sleep_fn: Any = None,
) -> Outcome:
    _sleep = sleep_fn if sleep_fn is not None else time.sleep
    allow_partial = node.attributes.get("allow_partial", False)

    for attempt in range(1, policy.max_attempts + 1):
        outcome = handler.handle(node, context, graph)

        if outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.PARTIAL_SUCCESS):
            return outcome

        if outcome.status == OutcomeStatus.FAIL:
            if attempt < policy.max_attempts:
                delay_ms = calculate_delay(policy.backoff, attempt, rng)
                if emitter:
                    emitter.emit(
                        "StageRetrying",
                        node_id=node.id,
                        attempt=attempt,
                        max_attempts=policy.max_attempts,
                        delay_ms=int(delay_ms),
                    )
                _sleep(delay_ms / 1000.0)
                continue
            return outcome

        if outcome.status == OutcomeStatus.RETRY:
            if attempt < policy.max_attempts:
                delay_ms = calculate_delay(policy.backoff, attempt, rng)
                if emitter:
                    emitter.emit(
                        "StageRetrying",
                        node_id=node.id,
                        attempt=attempt,
                        max_attempts=policy.max_attempts,
                        delay_ms=int(delay_ms),
                    )
                _sleep(delay_ms / 1000.0)
                continue
            else:
                if allow_partial:
                    return Outcome(
                        status=OutcomeStatus.PARTIAL_SUCCESS,
                        notes="retries exhausted, partial accepted",
                    )
                return Outcome(
                    status=OutcomeStatus.FAIL,
                    failure_reason="max retries exceeded",
                )

    return Outcome(status=OutcomeStatus.FAIL, failure_reason="max retries exceeded")
