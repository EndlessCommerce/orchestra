"""End-to-end integration tests for worktree-based parallel execution and resume.

These tests exercise the full pipeline: fan-out → worktree creation → agent file
writes → per-turn commits → fan-in → worktree merge → session branch with both
agents' commits.  Resume tests verify that checkpoints include workspace_snapshot
and that git state can be restored from those snapshots.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
from orchestra.engine.runner import PipelineRunner, _RunState
from orchestra.handlers.fan_in_handler import FanInHandler
from orchestra.handlers.parallel_handler import ParallelHandler
from orchestra.handlers.registry import HandlerRegistry
from orchestra.handlers.start import StartHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus
from orchestra.workspace import git_ops
from orchestra.workspace.commit_message import DeterministicCommitMessageGenerator
from orchestra.workspace.repo_context import RepoContext
from orchestra.workspace.restore import restore_git_state
from orchestra.workspace.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def _init_git_repo(path: Path) -> str:
    """Initialise a git repo with one commit and return the HEAD SHA."""
    path.mkdir(parents=True, exist_ok=True)
    git_ops.run_git("init", cwd=path)
    git_ops.run_git("config", "user.email", "test@test.com", cwd=path)
    git_ops.run_git("config", "user.name", "Test", cwd=path)
    (path / "README.md").write_text("# Project\n")
    git_ops.run_git("add", "README.md", cwd=path)
    git_ops.run_git("commit", "-m", "Initial commit", cwd=path)
    return git_ops.rev_parse("HEAD", cwd=path)


def _make_workspace_manager(
    repos: dict[str, Path],
    emitter: RecordingEmitter,
) -> WorkspaceManager:
    """Build a WorkspaceManager with repo contexts pre-populated."""
    repo_configs = {
        name: RepoConfig(path=str(path)) for name, path in repos.items()
    }
    config = OrchestraConfig(
        workspace=WorkspaceConfig(repos=repo_configs),
        config_dir=list(repos.values())[0].parent,
    )
    commit_gen = DeterministicCommitMessageGenerator()
    mgr = WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)

    # Directly populate _repo_contexts so we don't need full session setup
    for name, path in repos.items():
        branch = git_ops.current_branch(cwd=path)
        mgr._repo_contexts[name] = RepoContext(
            name=name,
            path=path,
            branch=branch,
            base_sha=git_ops.rev_parse("HEAD", cwd=path),
        )
    mgr._session_id = "e2e-session"
    mgr._pipeline_name = "e2e-pipeline"
    return mgr


class _FileWritingHandler:
    """A codergen handler that writes a file in the workspace repo.

    For parallel branches the node_id matches the branch_id (e.g., "A", "B"),
    so we look up the worktree specifically for that branch.  For sequential
    nodes we fall back to the repo path directly.
    """

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        repo_name: str = "project",
    ) -> None:
        self._ws = workspace_manager
        self._repo_name = repo_name

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        repo_ctx = self._ws._repo_contexts.get(self._repo_name)
        if repo_ctx is None:
            return Outcome(status=OutcomeStatus.FAIL, failure_reason="No repo context")

        # In parallel branches the node_id matches the branch_id, so look up
        # that branch's specific worktree.  Fall back to repo path for
        # sequential nodes.
        cwd = repo_ctx.path
        wt_contexts = self._ws._active_worktrees.get(node.id)
        if wt_contexts:
            wt_ctx = wt_contexts.get(self._repo_name)
            if wt_ctx and wt_ctx.worktree_path:
                cwd = wt_ctx.worktree_path
        elif repo_ctx.worktree_path:
            cwd = repo_ctx.worktree_path

        filename = f"{node.id}_output.txt"
        (cwd / filename).write_text(f"Output from {node.id}\n")
        git_ops.add([filename], cwd=cwd)
        git_ops.commit(
            f"Agent work in {node.id}",
            author=f"{node.id} <agent@test.com>",
            cwd=cwd,
        )

        return Outcome(
            status=OutcomeStatus.SUCCESS,
            notes=f"Wrote {filename}",
            context_updates={"last_response": f"Wrote {filename}"},
        )


def _two_branch_pipeline() -> PipelineGraph:
    # max_parallel=1 serializes branch execution so only one worktree is
    # active at a time.  The real system threads worktree RepoContexts into
    # each branch's repo tools; the test's simplified _FileWritingHandler uses
    # _resolve_commit_cwd which returns the first active worktree.
    return PipelineGraph(
        name="e2e_parallel",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component", attributes={"max_parallel": 1}),
            "A": Node(id="A", shape="box", prompt="Do A"),
            "B": Node(id="B", shape="box", prompt="Do B"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="exit"),
        ],
    )


def _linear_pipeline() -> PipelineGraph:
    return PipelineGraph(
        name="e2e_linear",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "step1": Node(id="step1", shape="box", prompt="Step 1"),
            "step2": Node(id="step2", shape="box", prompt="Step 2"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="step1"),
            Edge(from_node="step1", to_node="step2"),
            Edge(from_node="step2", to_node="exit"),
        ],
    )


# ===========================================================================
# Test 1: Parallel with worktrees — full lifecycle
# ===========================================================================


class TestParallelWithWorktrees:
    """Fan-out → 2 agents write in isolated worktrees → per-turn commits
    → fan-in → merge → session branch has both agents' commits."""

    def test_parallel_with_worktrees(self, tmp_path: Path) -> None:
        repo_path = tmp_path / "repo"
        _init_git_repo(repo_path)

        # Create session branch
        session_branch = "session/e2e-pipeline/e2e-session"
        git_ops.run_git("checkout", "-b", session_branch, cwd=repo_path)

        emitter = RecordingEmitter()
        ws_mgr = _make_workspace_manager({"project": repo_path}, emitter)

        file_handler = _FileWritingHandler(workspace_manager=ws_mgr)

        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", file_handler)
        registry.register(
            "component",
            ParallelHandler(
                handler_registry=registry,
                event_emitter=emitter,
                workspace_manager=ws_mgr,
            ),
        )
        registry.register(
            "tripleoctagon",
            FanInHandler(workspace_manager=ws_mgr),
        )

        graph = _two_branch_pipeline()
        runner = PipelineRunner(
            graph,
            registry,
            emitter,
            workspace_manager=ws_mgr,
        )
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify both agents' files are on the session branch after merge
        git_ops.checkout(session_branch, cwd=repo_path)
        assert (repo_path / "A_output.txt").exists()
        assert (repo_path / "B_output.txt").exists()
        assert (repo_path / "A_output.txt").read_text() == "Output from A\n"
        assert (repo_path / "B_output.txt").read_text() == "Output from B\n"

        # Verify worktree events were emitted
        event_types = [e[0] for e in emitter.events]
        assert "WorktreeCreated" in event_types
        assert "WorktreeMerged" in event_types

        # Verify checkpoint events include workspace_snapshot
        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        fan_in_cp = [cp for cp in checkpoints if cp[1].get("node_id") == "fan_in"]
        assert len(fan_in_cp) >= 1
        snapshot = fan_in_cp[0][1].get("workspace_snapshot", {})
        assert "project" in snapshot
        assert len(snapshot["project"]) == 40  # Full SHA


# ===========================================================================
# Test 2: Resume at node boundary — run → pause → resume → git correct
# ===========================================================================


class TestResumeAtNodeBoundaryE2E:
    """Run a pipeline, pause after step1, verify checkpoint has workspace_snapshot,
    restore git state, resume from step2, verify pipeline completes."""

    def test_resume_at_node_boundary_e2e(self, tmp_path: Path) -> None:
        repo_path = tmp_path / "repo"
        _init_git_repo(repo_path)

        session_branch = "session/e2e-pipeline/e2e-session"
        git_ops.run_git("checkout", "-b", session_branch, cwd=repo_path)

        emitter = RecordingEmitter()
        ws_mgr = _make_workspace_manager({"project": repo_path}, emitter)
        file_handler = _FileWritingHandler(workspace_manager=ws_mgr)

        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", file_handler)

        graph = _linear_pipeline()

        # --- Phase 1: Run and pause after step1 ---
        runner = PipelineRunner(
            graph, registry, emitter, workspace_manager=ws_mgr,
        )

        # Request pause to stop after step1 completes
        class _PauseAfterStep1:
            """Intercept StageCompleted for step1 and request pause."""
            def __init__(self, runner: PipelineRunner) -> None:
                self._runner = runner
                self._original_emit = emitter.emit

            def __enter__(self):
                def patched_emit(event_type: str, **data: Any) -> None:
                    self._original_emit(event_type, **data)
                    if event_type == "StageCompleted" and data.get("node_id") == "step1":
                        self._runner.request_pause()
                emitter.emit = patched_emit
                return self

            def __exit__(self, *args):
                emitter.emit = self._original_emit

        with _PauseAfterStep1(runner):
            first_outcome = runner.run(
                pipeline_name="e2e-pipeline",
                dot_file_path="/tmp/test.dot",
                graph_hash="deadbeef",
                session_display_id="e2e-session",
            )

        # Pipeline should have been paused
        assert first_outcome.status == OutcomeStatus.FAIL
        assert "paused" in (first_outcome.failure_reason or "").lower()

        # step1 should have created its file
        assert (repo_path / "step1_output.txt").exists()

        # Find the checkpoint after step1 — it should have workspace_snapshot
        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        step1_cp = [cp for cp in checkpoints if cp[1].get("node_id") == "step1"]
        assert len(step1_cp) >= 1
        ws_snapshot = step1_cp[0][1].get("workspace_snapshot", {})
        assert "project" in ws_snapshot

        step1_sha = ws_snapshot["project"]
        assert len(step1_sha) == 40

        # --- Phase 2: Simulate git state change (e.g., user checkout main) ---
        git_ops.checkout("main", cwd=repo_path)
        assert not (repo_path / "step1_output.txt").exists()

        # --- Phase 3: Restore git state and resume ---
        repos_config = {"project": RepoConfig(path=str(repo_path))}
        restore_git_state(ws_snapshot, repos_config, config_dir=tmp_path)

        # Git should be back at the checkpoint SHA
        assert git_ops.rev_parse("HEAD", cwd=repo_path) == step1_sha
        assert (repo_path / "step1_output.txt").exists()

        # Resume from step2
        emitter2 = RecordingEmitter()
        ws_mgr2 = _make_workspace_manager({"project": repo_path}, emitter2)
        file_handler2 = _FileWritingHandler(workspace_manager=ws_mgr2)

        registry2 = HandlerRegistry()
        registry2.register("Mdiamond", StartHandler())
        registry2.register("Msquare", ExitHandler())
        registry2.register("box", file_handler2)

        runner2 = PipelineRunner(
            graph, registry2, emitter2, workspace_manager=ws_mgr2,
        )

        # Build the resumed state (as restore_from_turns would)
        state = _RunState(
            context=Context(),
            completed_nodes=["start", "step1"],
            visited_outcomes={
                "start": OutcomeStatus.SUCCESS,
                "step1": OutcomeStatus.SUCCESS,
            },
        )
        step2_node = graph.get_node("step2")
        assert step2_node is not None

        resume_outcome = runner2.resume(
            state=state,
            next_node=step2_node,
            pipeline_name="e2e-pipeline",
        )

        assert resume_outcome.status == OutcomeStatus.SUCCESS

        # Both step1 and step2 files should exist
        assert (repo_path / "step1_output.txt").exists()
        assert (repo_path / "step2_output.txt").exists()


# ===========================================================================
# Test 3: Resume at agent turn — restore git to specific turn SHA
# ===========================================================================


class TestResumeAtAgentTurnE2E:
    """Run a pipeline that creates multiple commits, then restore git state
    to a specific earlier SHA (simulating agent-turn-level resume) and verify
    the repo is at the correct state."""

    def test_resume_at_agent_turn_e2e(self, tmp_path: Path) -> None:
        repo_path = tmp_path / "repo"
        _init_git_repo(repo_path)

        session_branch = "session/e2e-pipeline/e2e-session"
        git_ops.run_git("checkout", "-b", session_branch, cwd=repo_path)

        emitter = RecordingEmitter()
        ws_mgr = _make_workspace_manager({"project": repo_path}, emitter)
        file_handler = _FileWritingHandler(workspace_manager=ws_mgr)

        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", file_handler)

        graph = _linear_pipeline()
        runner = PipelineRunner(
            graph, registry, emitter, workspace_manager=ws_mgr,
        )

        outcome = runner.run()
        assert outcome.status == OutcomeStatus.SUCCESS

        # Both files should exist
        assert (repo_path / "step1_output.txt").exists()
        assert (repo_path / "step2_output.txt").exists()

        # Find the checkpoint after step1 to get the SHA at that point
        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        step1_cp = [cp for cp in checkpoints if cp[1].get("node_id") == "step1"]
        assert len(step1_cp) >= 1
        ws_snapshot = step1_cp[0][1].get("workspace_snapshot", {})
        assert "project" in ws_snapshot
        step1_sha = ws_snapshot["project"]

        # Simulate restoring to the agent turn's SHA (mid-pipeline state)
        repos_config = {"project": RepoConfig(path=str(repo_path))}
        restore_git_state(ws_snapshot, repos_config, config_dir=tmp_path)

        # Git should be at step1's SHA
        assert git_ops.rev_parse("HEAD", cwd=repo_path) == step1_sha

        # step1 file should exist, step2 should NOT (we're at an earlier point)
        assert (repo_path / "step1_output.txt").exists()
        assert not (repo_path / "step2_output.txt").exists()

        # Now resume from step2 with a fresh runner
        emitter2 = RecordingEmitter()
        ws_mgr2 = _make_workspace_manager({"project": repo_path}, emitter2)
        file_handler2 = _FileWritingHandler(workspace_manager=ws_mgr2)

        registry2 = HandlerRegistry()
        registry2.register("Mdiamond", StartHandler())
        registry2.register("Msquare", ExitHandler())
        registry2.register("box", file_handler2)

        runner2 = PipelineRunner(
            graph, registry2, emitter2, workspace_manager=ws_mgr2,
        )

        state = _RunState(
            context=Context(),
            completed_nodes=["start", "step1"],
            visited_outcomes={
                "start": OutcomeStatus.SUCCESS,
                "step1": OutcomeStatus.SUCCESS,
            },
        )
        step2_node = graph.get_node("step2")
        assert step2_node is not None

        resume_outcome = runner2.resume(
            state=state,
            next_node=step2_node,
            pipeline_name="e2e-pipeline",
        )

        assert resume_outcome.status == OutcomeStatus.SUCCESS
        assert (repo_path / "step1_output.txt").exists()
        assert (repo_path / "step2_output.txt").exists()
