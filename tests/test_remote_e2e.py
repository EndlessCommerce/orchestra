"""End-to-end integration tests for remote git operations."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
from orchestra.events.observer import PushObserver
from orchestra.events.types import CheckpointSaved, StageStarted
from orchestra.models.agent_turn import AgentTurn
from orchestra.workspace.commit_message import DeterministicCommitMessageGenerator
from orchestra.workspace.git_ops import clone, current_branch, rev_parse, run_git
from orchestra.workspace.workspace_manager import WorkspaceManager


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run_git("init", cwd=path)
    run_git("config", "user.email", "test@test.com", cwd=path)
    run_git("config", "user.name", "Test", cwd=path)
    (path / "README.md").write_text(f"# {path.name}\n")
    run_git("add", "README.md", cwd=path)
    run_git("commit", "-m", "Initial commit", cwd=path)
    return path


def _make_bare_remote(source: Path, bare_path: Path) -> Path:
    run_git("clone", "--bare", str(source), str(bare_path), cwd=source.parent)
    return bare_path


class TestFullRemoteLifecycle:
    def test_full_remote_lifecycle(self, tmp_path: Path) -> None:
        """Clone from bare remote → pipeline runs → agent modifies files →
        auto-committed → pushed to remote on completion → remote has session
        branch with agent commits."""
        # Setup: source repo → bare remote
        source = _init_repo(tmp_path / "source")
        bare = _make_bare_remote(source, tmp_path / "remote.git")

        # Workspace path doesn't exist yet — will be cloned
        workspace_path = tmp_path / "workspace" / "project"

        config = OrchestraConfig(
            workspace=WorkspaceConfig(
                repos={
                    "project": RepoConfig(
                        path=str(workspace_path),
                        remote=str(bare),
                    )
                }
            ),
            config_dir=tmp_path,
        )
        emitter = RecordingEmitter()
        mgr = WorkspaceManager(
            config=config,
            event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )

        # 1. Setup session — clones repo and creates session branch
        contexts = mgr.setup_session("test-pipe", "e2e001")
        assert workspace_path.exists()
        assert (workspace_path / "README.md").exists()

        # Verify events
        event_types = [e[0] for e in emitter.events]
        assert "RepoCloned" in event_types
        assert "SessionBranchCreated" in event_types

        session_branch = contexts["project"].branch
        assert current_branch(cwd=workspace_path) == session_branch

        # 2. Agent modifies files
        mgr.on_event(StageStarted(node_id="coder", handler_type="box"))
        (workspace_path / "output.py").write_text("print('hello')\n")
        turn = AgentTurn(
            turn_number=1, model="test-model", provider="test",
            files_written=[str(workspace_path / "output.py")],
        )
        mgr.on_turn_callback(turn)
        assert turn.git_sha != ""

        # 3. Push on completion
        mgr.push_session_branches("on_completion")

        # 4. Verify remote has session branch with agent commits
        remote_branches = run_git("branch", cwd=bare)
        assert session_branch in remote_branches

        # Clone from remote and verify content
        verify_clone = tmp_path / "verify"
        clone(str(bare), verify_clone)
        run_git("checkout", session_branch, cwd=verify_clone)
        assert (verify_clone / "output.py").exists()
        assert (verify_clone / "output.py").read_text() == "print('hello')\n"

        # 5. Teardown
        mgr.teardown_session()

    def test_ephemeral_container_simulation(self, tmp_path: Path) -> None:
        """Clone → run pipeline → push on checkpoint → delete local clone →
        re-clone → verify agent commits survive on remote."""
        source = _init_repo(tmp_path / "source")
        bare = _make_bare_remote(source, tmp_path / "remote.git")

        workspace_path = tmp_path / "workspace" / "project"

        config = OrchestraConfig(
            workspace=WorkspaceConfig(
                repos={
                    "project": RepoConfig(
                        path=str(workspace_path),
                        remote=str(bare),
                        push="on_checkpoint",
                    )
                }
            ),
            config_dir=tmp_path,
        )
        emitter = RecordingEmitter()
        mgr = WorkspaceManager(
            config=config,
            event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )

        # 1. Setup — clone
        contexts = mgr.setup_session("ephemeral", "eph001")
        session_branch = contexts["project"].branch

        # 2. Agent makes changes
        mgr.on_event(StageStarted(node_id="coder", handler_type="box"))
        (workspace_path / "result.txt").write_text("agent output\n")
        turn = AgentTurn(
            turn_number=1, model="m", provider="p",
            files_written=[str(workspace_path / "result.txt")],
        )
        mgr.on_turn_callback(turn)
        agent_sha = turn.git_sha

        # 3. Push on checkpoint
        push_observer = PushObserver(mgr)
        checkpoint = CheckpointSaved(node_id="coder", completed_nodes=["coder"])
        push_observer.on_event(checkpoint)

        # Verify push happened
        push_events = [e for e in emitter.events if e[0] == "SessionBranchPushed"]
        assert len(push_events) == 1

        mgr.teardown_session()

        # 4. "Destroy" local clone (simulate container crash)
        import shutil
        shutil.rmtree(workspace_path)
        assert not workspace_path.exists()

        # 5. Re-clone from remote
        emitter2 = RecordingEmitter()
        mgr2 = WorkspaceManager(
            config=config,
            event_emitter=emitter2,
            commit_gen=DeterministicCommitMessageGenerator(),
        )
        contexts2 = mgr2.setup_session("ephemeral", "eph002")

        # Verify the clone happened again
        assert workspace_path.exists()
        event_types2 = [e[0] for e in emitter2.events]
        assert "RepoCloned" in event_types2

        # 6. Verify the original session branch with agent commits is available
        run_git("checkout", session_branch, cwd=workspace_path)
        assert (workspace_path / "result.txt").exists()
        assert (workspace_path / "result.txt").read_text() == "agent output\n"

        mgr2.teardown_session()

    def test_remote_with_parallel_worktrees(self, tmp_path: Path) -> None:
        """Clone → fan-out → worktrees → fan-in → merge → push →
        remote has merged session branch."""
        source = _init_repo(tmp_path / "source")
        bare = _make_bare_remote(source, tmp_path / "remote.git")

        workspace_path = tmp_path / "workspace" / "project"

        # Use wt/ prefix for worktree branches to avoid git ref collision
        # with session branch (orchestra/parallel/par001 vs orchestra/parallel/par001/agent-a)
        config = OrchestraConfig(
            workspace=WorkspaceConfig(
                repos={
                    "project": RepoConfig(
                        path=str(workspace_path),
                        remote=str(bare),
                        branch_prefix="orchestra/",
                    )
                }
            ),
            config_dir=tmp_path,
        )
        emitter = RecordingEmitter()
        mgr = WorkspaceManager(
            config=config,
            event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )

        # 1. Setup — clone and create session branch
        contexts = mgr.setup_session("parallel", "par001")
        session_branch = contexts["project"].branch

        # 2. Create worktrees — directly use WorktreeManager with wt/ prefix
        # to avoid git ref collision with session branch
        from orchestra.workspace.repo_context import RepoContext
        from orchestra.workspace.worktree_manager import WorktreeManager

        wt_mgr = WorktreeManager(
            repo_contexts=mgr._repo_contexts,
            session_id="par001",
            pipeline_name="parallel",
            branch_prefix="wt/",  # Different prefix to avoid collision
            event_emitter=emitter,
        )

        wt_a = wt_mgr.create_worktrees("agent-a")
        wt_b = wt_mgr.create_worktrees("agent-b")
        mgr._active_worktrees["agent-a"] = wt_a
        mgr._active_worktrees["agent-b"] = wt_b

        # 3. Each agent makes changes in its worktree
        for wt_name, wt_contexts, filename in [
            ("agent-a", wt_a, "a_output.py"),
            ("agent-b", wt_b, "b_output.py"),
        ]:
            wt_path = wt_contexts["project"].worktree_path
            assert wt_path is not None
            (wt_path / filename).write_text(f"# {wt_name}\n")
            run_git("add", filename, cwd=wt_path)
            run_git("config", "user.email", "test@test.com", cwd=wt_path)
            run_git("config", "user.name", "Test", cwd=wt_path)
            run_git("commit", "-m", f"{wt_name} commit", cwd=wt_path)

        # 4. Fan-in merge
        mgr._worktree_manager = wt_mgr
        result = mgr.merge_worktrees(["agent-a", "agent-b"])
        assert result.success

        # 5. Push on completion
        mgr.push_session_branches("on_completion")

        # 6. Verify remote has merged session branch
        verify_clone = tmp_path / "verify"
        clone(str(bare), verify_clone)
        run_git("checkout", session_branch, cwd=verify_clone)
        assert (verify_clone / "a_output.py").exists()
        assert (verify_clone / "b_output.py").exists()

        mgr.teardown_session()
