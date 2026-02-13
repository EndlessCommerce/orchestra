"""End-to-end integration tests for workspace lifecycle."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
from orchestra.events.types import StageStarted
from orchestra.models.agent_turn import AgentTurn
from orchestra.workspace.commit_message import DeterministicCommitMessageGenerator
from orchestra.workspace.git_ops import current_branch, log, rev_parse, run_git
from orchestra.workspace.on_turn import build_on_turn_callback
from orchestra.workspace.workspace_manager import WorkspaceManager


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def _init_repo(path: Path) -> Path:
    path.mkdir(exist_ok=True)
    run_git("init", cwd=path)
    run_git("config", "user.email", "test@test.com", cwd=path)
    run_git("config", "user.name", "Test", cwd=path)
    (path / "README.md").write_text(f"# {path.name}\n")
    run_git("add", "README.md", cwd=path)
    run_git("commit", "-m", "Initial commit", cwd=path)
    return path


class TestFullWorkspaceLifecycle:
    def test_full_lifecycle(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "repo")
        original_branch = current_branch(cwd=repo)
        original_sha = rev_parse("HEAD", cwd=repo)

        config = OrchestraConfig(
            workspace=WorkspaceConfig(repos={"project": RepoConfig(path=str(repo))}),
            config_dir=tmp_path,
        )
        emitter = RecordingEmitter()
        manager = WorkspaceManager(
            config=config, event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )

        # 1. Setup session — branch created
        contexts = manager.setup_session("test-pipe", "sess1")
        assert current_branch(cwd=repo) != original_branch
        assert current_branch(cwd=repo) == contexts["project"].branch

        # 2. Agent modifies files across turns
        manager.on_event(StageStarted(node_id="code", handler_type="box"))
        shas = []
        for i in range(2):
            f = repo / f"output_{i}.py"
            f.write_text(f"content_{i}\n")
            turn = AgentTurn(
                turn_number=i + 1, model="m", provider="p",
                files_written=[str(f)],
            )
            manager.on_turn_callback(turn)
            shas.append(turn.git_sha)

        # 3. Per-turn commits with metadata
        assert len(set(shas)) == 2
        for sha in shas:
            assert len(sha) == 40

        # 4. CXDB events with SHAs
        turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
        assert len(turn_events) == 2
        for te in turn_events:
            assert te[1]["git_sha"] != ""

        # 5. Pipeline completes — original branch restored
        manager.teardown_session()
        assert current_branch(cwd=repo) == original_branch

        # 6. Session branch still exists
        branches = run_git("branch", "--list", cwd=repo)
        assert contexts["project"].branch in branches

        # 7. Original branch unchanged
        assert rev_parse("HEAD", cwd=repo) == original_sha


class TestMultiRepoLifecycle:
    def test_two_repos_separate_branches(self, tmp_path: Path) -> None:
        backend = _init_repo(tmp_path / "backend")
        frontend = _init_repo(tmp_path / "frontend")

        config = OrchestraConfig(
            workspace=WorkspaceConfig(repos={
                "backend": RepoConfig(path=str(backend)),
                "frontend": RepoConfig(path=str(frontend)),
            }),
            config_dir=tmp_path,
        )
        emitter = RecordingEmitter()
        manager = WorkspaceManager(
            config=config, event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )

        contexts = manager.setup_session("multi", "sess")
        # Branch names are the same string but in different repos
        assert contexts["backend"].branch == contexts["frontend"].branch
        assert current_branch(cwd=backend) == contexts["backend"].branch
        assert current_branch(cwd=frontend) == contexts["frontend"].branch
        # But they are in different repo paths
        assert contexts["backend"].path != contexts["frontend"].path

        branch_events = [e for e in emitter.events if e[0] == "SessionBranchCreated"]
        assert len(branch_events) == 2

        manager.teardown_session()


class TestPipelineFailureRestoresBranches:
    def test_teardown_on_failure(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "repo")
        original = current_branch(cwd=repo)

        config = OrchestraConfig(
            workspace=WorkspaceConfig(repos={"project": RepoConfig(path=str(repo))}),
            config_dir=tmp_path,
        )
        emitter = RecordingEmitter()
        manager = WorkspaceManager(
            config=config, event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )

        manager.setup_session("pipe", "sess")
        assert current_branch(cwd=repo) != original

        # Simulate failure — teardown should still work
        manager.teardown_session()
        assert current_branch(cwd=repo) == original


class TestNoWorkspacePipeline:
    def test_agent_turn_completed_still_emitted(self) -> None:
        emitter = RecordingEmitter()
        callback = build_on_turn_callback(emitter, workspace_manager=None)

        turn = AgentTurn(
            turn_number=1, model="m", provider="p",
            files_written=["a.py"],
            token_usage={"input": 10},
        )
        callback(turn)

        turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
        assert len(turn_events) == 1
        data = turn_events[0][1]
        assert data["files_written"] == ["a.py"]
        assert data["git_sha"] == ""
        assert data["model"] == "m"
