from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from orchestra.engine.error_policies import ErrorPolicy
from orchestra.engine.graph_analysis import extract_branch_subgraphs, find_fan_in_node
from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.engine.runner import EventEmitter
    from orchestra.handlers.registry import HandlerRegistry


class ParallelHandler:
    def __init__(
        self,
        handler_registry: HandlerRegistry,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self._registry = handler_registry
        self._emitter = event_emitter

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        fan_in_id = find_fan_in_node(graph, node.id)
        if fan_in_id is None:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=f"No fan-in node found for parallel node '{node.id}'",
            )

        branches = extract_branch_subgraphs(graph, node.id, fan_in_id)

        error_policy_str = node.attributes.get("error_policy", "continue")
        error_policy = ErrorPolicy(error_policy_str)
        max_parallel = node.attributes.get("max_parallel")
        if max_parallel is not None:
            max_parallel = int(max_parallel)

        self._emit("ParallelStarted", node_id=node.id, branch_count=len(branches))

        parallel_start = time.monotonic()
        results = asyncio.run(
            self._execute_branches(
                branches=branches,
                parent_context=context,
                error_policy=error_policy,
                max_parallel=max_parallel,
                fan_out_node_id=node.id,
            )
        )
        parallel_duration_ms = int((time.monotonic() - parallel_start) * 1000)

        success_count = sum(
            1 for o in results.values()
            if o.status in (OutcomeStatus.SUCCESS, OutcomeStatus.PARTIAL_SUCCESS)
        )
        failure_count = len(results) - success_count

        self._emit(
            "ParallelCompleted",
            node_id=node.id,
            success_count=success_count,
            failure_count=failure_count,
            duration_ms=parallel_duration_ms,
        )

        return Outcome(
            status=OutcomeStatus.SUCCESS if success_count > 0 else OutcomeStatus.FAIL,
            context_updates={"parallel.results": results},
            suggested_next_ids=[fan_in_id],
        )

    async def _execute_branches(
        self,
        branches: dict[str, Any],
        parent_context: Context,
        error_policy: ErrorPolicy,
        max_parallel: int | None,
        fan_out_node_id: str,
    ) -> dict[str, Outcome]:
        from orchestra.engine.runner import PipelineRunner

        semaphore = asyncio.Semaphore(max_parallel) if max_parallel else None
        results: dict[str, Outcome] = {}
        cancel_flag = False

        async def run_branch(branch_id: str, info: Any) -> tuple[str, Outcome]:
            nonlocal cancel_flag
            if cancel_flag:
                return branch_id, Outcome(
                    status=OutcomeStatus.FAIL,
                    failure_reason="Cancelled by fail_fast policy",
                )

            if semaphore:
                await semaphore.acquire()

            try:
                branch_context = parent_context.clone()
                self._emit(
                    "ParallelBranchStarted",
                    node_id=fan_out_node_id,
                    branch_id=branch_id,
                    first_node_id=info.first_node_id,
                )

                branch_start = time.monotonic()
                runner = PipelineRunner(
                    graph=info.subgraph,
                    handler_registry=self._registry,
                    event_emitter=self._emitter or _NullEmitter(),
                )

                loop = asyncio.get_event_loop()
                outcome = await loop.run_in_executor(
                    None,
                    lambda: runner.run(context=branch_context, pipeline_name=f"branch_{branch_id}"),
                )
                branch_duration_ms = int((time.monotonic() - branch_start) * 1000)

                self._emit(
                    "ParallelBranchCompleted",
                    node_id=fan_out_node_id,
                    branch_id=branch_id,
                    status=outcome.status.value,
                    duration_ms=branch_duration_ms,
                    failure_reason=outcome.failure_reason,
                )

                if error_policy == ErrorPolicy.FAIL_FAST and outcome.status == OutcomeStatus.FAIL:
                    cancel_flag = True

                return branch_id, outcome
            finally:
                if semaphore:
                    semaphore.release()

        tasks = [
            asyncio.ensure_future(run_branch(bid, info))
            for bid, info in branches.items()
        ]

        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                continue
            branch_id, outcome = item
            if error_policy == ErrorPolicy.IGNORE and outcome.status == OutcomeStatus.FAIL:
                continue
            results[branch_id] = outcome

        return results

    def _emit(self, event_type: str, **data: Any) -> None:
        if self._emitter is not None:
            self._emitter.emit(event_type, **data)


class _NullEmitter:
    def emit(self, event_type: str, **data: Any) -> None:
        pass
