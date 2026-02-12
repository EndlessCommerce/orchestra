from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Any, Protocol

from orchestra.engine.edge_selection import select_edge
from orchestra.engine.failure_routing import resolve_failure_target
from orchestra.engine.goal_gates import check_goal_gates
from orchestra.engine.retry import build_retry_policy, execute_with_retry
from orchestra.models.context import Context
from orchestra.models.graph import PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.handlers.registry import HandlerRegistry


class EventEmitter(Protocol):
    def emit(self, event_type: str, **data: Any) -> None: ...


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
        context = Context()
        context.set("graph.goal", self._graph.goal)
        completed_nodes: list[str] = []

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
        visited_outcomes: dict[str, OutcomeStatus] = {}
        max_reroutes = int(self._graph.graph_attributes.get("default_max_retry", 50))
        reroute_count = 0

        while True:
            node = self._graph.get_node(current_node.id)
            if node is None:
                raise RuntimeError(f"Node '{current_node.id}' not found in graph")

            if node.shape == "Msquare":
                handler = self._registry.get(node.shape)
                if handler:
                    handler.handle(node, context, self._graph)

                gate_result = check_goal_gates(visited_outcomes, self._graph)
                if not gate_result.satisfied:
                    if gate_result.reroute_target is not None:
                        if reroute_count >= max_reroutes:
                            pipeline_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
                            self._emitter.emit(
                                "PipelineFailed",
                                pipeline_name=self._graph.name,
                                error="Max reroutes exceeded for goal gate enforcement",
                                duration_ms=pipeline_duration_ms,
                            )
                            return Outcome(
                                status=OutcomeStatus.FAIL,
                                failure_reason="Max reroutes exceeded for goal gate enforcement",
                            )
                        reroute_count += 1
                        target_node = self._graph.get_node(gate_result.reroute_target)
                        if target_node is not None:
                            current_node = target_node
                            continue

                    pipeline_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
                    self._emitter.emit(
                        "PipelineFailed",
                        pipeline_name=self._graph.name,
                        error="Goal gate unsatisfied and no valid reroute target",
                        duration_ms=pipeline_duration_ms,
                    )
                    return Outcome(
                        status=OutcomeStatus.FAIL,
                        failure_reason="Goal gate unsatisfied and no valid reroute target",
                    )
                break

            handler = self._registry.get(node.shape)
            if handler is None:
                raise RuntimeError(f"No handler for shape '{node.shape}' on node '{node.id}'")

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
                context=context,
                graph=self._graph,
                policy=retry_policy,
                emitter=self._emitter,
                rng=self._rng,
                sleep_fn=self._sleep_fn,
            )
            stage_duration_ms = int((time.monotonic() - stage_start) * 1000)

            completed_nodes.append(node.id)
            visited_outcomes[node.id] = outcome.status

            for key, value in outcome.context_updates.items():
                context.set(key, value)
            context.set("outcome", outcome.status.value)
            context.set("current_node", node.id)
            context.set("last_stage", node.id)

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
                completed_nodes=list(completed_nodes),
                context_snapshot=context.snapshot(),
                retry_counters={},
            )

            last_outcome = outcome

            next_edge = select_edge(node.id, outcome, context, self._graph)
            if next_edge is not None:
                next_node = self._graph.get_node(next_edge.to_node)
                if next_node is None:
                    raise RuntimeError(f"Edge target node '{next_edge.to_node}' not found")
                current_node = next_node
                continue

            if outcome.status in (OutcomeStatus.FAIL, OutcomeStatus.RETRY):
                failure_target = resolve_failure_target(node, self._graph, outcome, context)
                if failure_target is not None:
                    target_node = self._graph.get_node(failure_target)
                    if target_node is not None:
                        current_node = target_node
                        continue

                pipeline_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
                self._emitter.emit(
                    "PipelineFailed",
                    pipeline_name=self._graph.name,
                    error=outcome.failure_reason or "Stage failed with no outgoing edge",
                    duration_ms=pipeline_duration_ms,
                )
                return outcome
            break

        pipeline_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
        self._emitter.emit(
            "PipelineCompleted",
            pipeline_name=self._graph.name,
            duration_ms=pipeline_duration_ms,
        )

        return last_outcome
