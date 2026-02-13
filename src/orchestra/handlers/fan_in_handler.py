from __future__ import annotations

from typing import TYPE_CHECKING, Any

from orchestra.engine.join_policies import JoinPolicy, evaluate_join
from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.backends.protocol import CodergenBackend
    from orchestra.workspace.workspace_manager import WorkspaceManager

_STATUS_PRIORITY = {
    OutcomeStatus.SUCCESS: 0,
    OutcomeStatus.PARTIAL_SUCCESS: 1,
    OutcomeStatus.RETRY: 2,
    OutcomeStatus.FAIL: 3,
}


class FanInHandler:
    def __init__(
        self,
        backend: CodergenBackend | None = None,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        self._backend = backend
        self._workspace_manager = workspace_manager

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        raw_results: dict[str, Any] = context.get("parallel.results", {})
        results: dict[str, Outcome] = {
            bid: Outcome.model_validate(v) if isinstance(v, dict) else v
            for bid, v in raw_results.items()
        }

        policy_str = node.attributes.get("join_policy", "wait_all")
        policy = JoinPolicy(policy_str)

        params: dict[str, Any] = {}
        if "k" in node.attributes:
            params["k"] = node.attributes["k"]
        if "quorum_percent" in node.attributes:
            params["quorum_percent"] = node.attributes["quorum_percent"]

        join_result = evaluate_join(policy, results, params)

        if not join_result.satisfied:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=join_result.failure_reason,
            )

        if node.prompt and self._backend is not None:
            best_id, best_outcome = self._select_via_llm(node, context, join_result.selected_results)
        else:
            best_id, best_outcome = self._select_heuristic(join_result.selected_results)

        context_updates: dict[str, Any] = {
            "parallel.fan_in.best_id": best_id,
            "parallel.fan_in.best_outcome": best_outcome.model_dump(),
            "parallel.fan_in.selected_results": [
                (bid, o.model_dump()) for bid, o in join_result.selected_results
            ],
        }

        # Merge worktrees at fan-in if workspace is configured
        if self._workspace_manager is not None:
            branch_ids = context.get("parallel.branch_ids", [])
            if branch_ids:
                merge_result = self._workspace_manager.merge_worktrees(branch_ids)
                if not merge_result.success:
                    context_updates["parallel.merge_conflicts"] = merge_result.conflicts
                    return Outcome(
                        status=OutcomeStatus.PARTIAL_SUCCESS,
                        context_updates=context_updates,
                    )

        return Outcome(
            status=join_result.status,
            context_updates=context_updates,
        )

    def _select_heuristic(
        self, candidates: list[tuple[str, Outcome]]
    ) -> tuple[str, Outcome]:
        def sort_key(item: tuple[str, Outcome]) -> tuple[int, float, str]:
            bid, outcome = item
            priority = _STATUS_PRIORITY.get(outcome.status, 99)
            score = outcome.context_updates.get("score", 0)
            return (priority, -score, bid)

        sorted_candidates = sorted(candidates, key=sort_key)
        return sorted_candidates[0]

    def _select_via_llm(
        self,
        node: Node,
        context: Context,
        candidates: list[tuple[str, Outcome]],
    ) -> tuple[str, Outcome]:
        assert self._backend is not None
        candidate_summary = "\n".join(
            f"- Branch '{bid}': status={o.status.value}, notes={o.notes}"
            for bid, o in candidates
        )
        prompt = f"{node.prompt}\n\nCandidates:\n{candidate_summary}\n\nSelect the best branch ID."
        result = self._backend.run(node=node, prompt=prompt, context=context)

        for bid, outcome in candidates:
            if bid in result.notes:
                return bid, outcome

        return self._select_heuristic(candidates)
