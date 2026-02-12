from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from orchestra.engine.edge_selection import select_edge
from orchestra.engine.failure_routing import resolve_failure_target
from orchestra.engine.goal_gates import check_goal_gates
from orchestra.engine.retry import build_retry_policy, execute_with_retry
from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.handlers.base import NodeHandler
    from orchestra.handlers.registry import HandlerRegistry


class EventEmitter(Protocol):
    def emit(self, event_type: str, **data: Any) -> None: ...


@dataclass
class _RunState:
    context: Context
    completed_nodes: list[str] = field(default_factory=list)
    visited_outcomes: dict[str, OutcomeStatus] = field(default_factory=dict)
    retry_counters: dict[str, int] = field(default_factory=dict)
    reroute_count: int = 0


class PipelineRunner:
    def __init__(
        self,
        graph: PipelineGraph,
        handler_registry: HandlerRegistry,
        event_emitter: EventEmitter,
        rng: random.Random | None = None,
        sleep_fn: Any = None,
    ) -> None:
        self._graph = graph
        self._registry = handler_registry
        self._emitter = event_emitter
        self._rng = rng
        self._sleep_fn = sleep_fn

    def run(self) -> Outcome:
        state = _RunState(context=Context())
        state.context.set("graph.goal", self._graph.goal)

        self._emitter.emit(
            "PipelineStarted",
            pipeline_name=self._graph.name,
            goal=self._graph.goal,
        )

        pipeline_start = time.monotonic()
        start_node = self._graph.get_start_node()
        if start_node is None:
            raise RuntimeError("No start node found in graph")

        current_node = start_node
        last_outcome = Outcome(status=OutcomeStatus.SUCCESS)
        max_reroutes = int(self._graph.graph_attributes.get("default_max_retry", 50))

        while True:
            node = self._graph.get_node(current_node.id)
            if node is None:
                raise RuntimeError(f"Node '{current_node.id}' not found in graph")

            if node.shape == "Msquare":
                handler = self._registry.get(node.shape)
                if handler:
                    handler.handle(node, state.context, self._graph)

                next_node = self._check_exit_gates(state, pipeline_start, max_reroutes)
                if next_node is not None:
                    current_node = next_node
                    continue
                if next_node is None and not check_goal_gates(state.visited_outcomes, self._graph).satisfied:
                    return Outcome(
                        status=OutcomeStatus.FAIL,
                        failure_reason="Goal gate unsatisfied and no valid reroute target",
                    )
                break

            handler = self._registry.get(node.shape)
            if handler is None:
                raise RuntimeError(f"No handler for shape '{node.shape}' on node '{node.id}'")

            outcome = self._execute_node(node, handler, state)
            last_outcome = outcome

            next_edge = select_edge(node.id, outcome, state.context, self._graph)
            if next_edge is not None:
                next_node_obj = self._graph.get_node(next_edge.to_node)
                if next_node_obj is None:
                    raise RuntimeError(f"Edge target node '{next_edge.to_node}' not found")
                current_node = next_node_obj
                continue

            if outcome.status in (OutcomeStatus.FAIL, OutcomeStatus.RETRY):
                failure_next = self._handle_node_failure(node, outcome, state, pipeline_start)
                if failure_next is not None:
                    current_node = failure_next
                    continue
                return outcome
            break

        pipeline_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
        self._emitter.emit(
            "PipelineCompleted",
            pipeline_name=self._graph.name,
            duration_ms=pipeline_duration_ms,
        )

        return last_outcome

    def _execute_node(self, node: Node, handler: NodeHandler, state: _RunState) -> Outcome:
        self._emitter.emit(
            "StageStarted",
            node_id=node.id,
            handler_type=node.shape,
        )

        stage_start = time.monotonic()
        retry_policy = build_retry_policy(node, self._graph)
        outcome = execute_with_retry(
            node=node,
            handler=handler,
            context=state.context,
            graph=self._graph,
            policy=retry_policy,
            emitter=self._emitter,
            rng=self._rng,
            sleep_fn=self._sleep_fn,
        )
        stage_duration_ms = int((time.monotonic() - stage_start) * 1000)

        state.completed_nodes.append(node.id)
        state.visited_outcomes[node.id] = outcome.status

        for key, value in outcome.context_updates.items():
            state.context.set(key, value)
        state.context.set("outcome", outcome.status.value)
        state.context.set("current_node", node.id)
        state.context.set("last_stage", node.id)

        if outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.PARTIAL_SUCCESS):
            self._emitter.emit(
                "StageCompleted",
                node_id=node.id,
                handler_type=node.shape,
                status=outcome.status.value,
                duration_ms=stage_duration_ms,
                prompt=node.prompt,
                response=outcome.notes,
                outcome=outcome.status.value,
            )
        else:
            self._emitter.emit(
                "StageFailed",
                node_id=node.id,
                handler_type=node.shape,
                error=outcome.failure_reason or outcome.notes,
            )

        self._emitter.emit(
            "CheckpointSaved",
            node_id=node.id,
            completed_nodes=list(state.completed_nodes),
            context_snapshot=state.context.snapshot(),
            retry_counters=dict(state.retry_counters),
        )

        return outcome

    def _handle_node_failure(
        self, node: Node, outcome: Outcome, state: _RunState, pipeline_start: float
    ) -> Node | None:
        failure_target = resolve_failure_target(node, self._graph, outcome, state.context)
        if failure_target is not None:
            target_node = self._graph.get_node(failure_target)
            if target_node is not None:
                return target_node

        pipeline_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
        self._emitter.emit(
            "PipelineFailed",
            pipeline_name=self._graph.name,
            error=outcome.failure_reason or "Stage failed with no outgoing edge",
            duration_ms=pipeline_duration_ms,
        )
        return None

    def _check_exit_gates(
        self, state: _RunState, pipeline_start: float, max_reroutes: int
    ) -> Node | None:
        gate_result = check_goal_gates(state.visited_outcomes, self._graph)
        if gate_result.satisfied:
            return None

        if gate_result.reroute_target is not None:
            if state.reroute_count >= max_reroutes:
                pipeline_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
                self._emitter.emit(
                    "PipelineFailed",
                    pipeline_name=self._graph.name,
                    error="Max reroutes exceeded for goal gate enforcement",
                    duration_ms=pipeline_duration_ms,
                )
                return None

            state.reroute_count += 1
            target_node = self._graph.get_node(gate_result.reroute_target)
            if target_node is not None:
                return target_node

        pipeline_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
        self._emitter.emit(
            "PipelineFailed",
            pipeline_name=self._graph.name,
            error="Goal gate unsatisfied and no valid reroute target",
            duration_ms=pipeline_duration_ms,
        )
        return None
