from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
from orchestra.events.types import StageCompleted, StageStarted
from orchestra.models.agent_turn import AgentTurn
from orchestra.workspace.commit_message import DeterministicCommitMessageGenerator
from orchestra.workspace.git_ops import current_branch, log, rev_parse, run_git
from orchestra.workspace.workspace_manager import WorkspaceManager


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git("init", cwd=repo)
    run_git("config", "user.email", "test@test.com", cwd=repo)
    run_git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("# Hello\n")
    run_git("add", "README.md", cwd=repo)
    run_git("commit", "-m", "Initial commit", cwd=repo)
    return repo


@pytest.fixture()
def config(git_repo: Path) -> OrchestraConfig:
    return OrchestraConfig(
        workspace=WorkspaceConfig(
            repos={"project": RepoConfig(path=str(git_repo))}
        ),
        config_dir=git_repo.parent,
    )


@pytest.fixture()
def emitter() -> RecordingEmitter:
    return RecordingEmitter()


@pytest.fixture()
def commit_gen() -> DeterministicCommitMessageGenerator:
    return DeterministicCommitMessageGenerator()


@pytest.fixture()
def manager(
    config: OrchestraConfig,
    emitter: RecordingEmitter,
    commit_gen: DeterministicCommitMessageGenerator,
) -> WorkspaceManager:
    return WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)


class TestSetupSession:
    def test_creates_branches(self, manager: WorkspaceManager, git_repo: Path) -> None:
        contexts = manager.setup_session("pipe", "sess1")
        assert "project" in contexts
        assert current_branch(cwd=git_repo) == contexts["project"].branch

    def test_emits_branch_created_events(self, manager: WorkspaceManager, emitter: RecordingEmitter) -> None:
        manager.setup_session("pipe", "sess1")
        branch_events = [e for e in emitter.events if e[0] == "SessionBranchCreated"]
        assert len(branch_events) == 1
        assert branch_events[0][1]["repo_name"] == "project"

    def test_returns_repo_contexts(self, manager: WorkspaceManager) -> None:
        contexts = manager.setup_session("pipe", "sess1")
        ctx = contexts["project"]
        assert ctx.name == "project"
        assert ctx.branch.startswith("orchestra/")
        assert len(ctx.base_sha) == 40


class TestTeardownSession:
    def test_restores_original_branch(self, manager: WorkspaceManager, git_repo: Path) -> None:
        original = current_branch(cwd=git_repo)
        manager.setup_session("pipe", "sess1")
        assert current_branch(cwd=git_repo) != original
        manager.teardown_session()
        assert current_branch(cwd=git_repo) == original

    def test_idempotent(self, manager: WorkspaceManager, git_repo: Path) -> None:
        original = current_branch(cwd=git_repo)
        manager.setup_session("pipe", "sess1")
        manager.teardown_session()
        manager.teardown_session()
        assert current_branch(cwd=git_repo) == original


class TestOnTurnWithWrites:
    def test_commits_files(self, manager: WorkspaceManager, git_repo: Path) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        new_file = git_repo / "new.py"
        new_file.write_text("print('hello')\n")

        turn = AgentTurn(
            turn_number=1,
            model="test-model",
            provider="test-provider",
            files_written=[str(new_file)],
        )
        manager.on_turn_callback(turn)

        assert turn.git_sha != ""
        assert len(turn.git_sha) == 40
        assert turn.commit_message != ""

    def test_correct_author(self, manager: WorkspaceManager, git_repo: Path) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="coder", handler_type="box"))

        new_file = git_repo / "a.txt"
        new_file.write_text("a\n")

        turn = AgentTurn(
            turn_number=1,
            model="claude-3.5",
            provider="anthropic",
            files_written=[str(new_file)],
        )
        manager.on_turn_callback(turn)

        author = log(1, fmt="%an <%ae>", cwd=git_repo)
        assert "coder (claude-3.5)" in author
        assert "orchestra@local" in author

    def test_correct_trailers(self, manager: WorkspaceManager, git_repo: Path) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        new_file = git_repo / "b.txt"
        new_file.write_text("b\n")

        turn = AgentTurn(
            turn_number=2,
            model="gpt-4o",
            provider="openai",
            files_written=[str(new_file)],
        )
        manager.on_turn_callback(turn)

        commit_body = log(1, fmt="%B", cwd=git_repo)
        assert "Orchestra-Model: gpt-4o" in commit_body
        assert "Orchestra-Provider: openai" in commit_body
        assert "Orchestra-Node: code" in commit_body
        assert "Orchestra-Pipeline: pipe" in commit_body
        assert "Orchestra-Session: sess1" in commit_body
        assert "Orchestra-Turn: 2" in commit_body

    def test_emits_commit_event(self, manager: WorkspaceManager, git_repo: Path, emitter: RecordingEmitter) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        new_file = git_repo / "c.txt"
        new_file.write_text("c\n")

        turn = AgentTurn(turn_number=1, model="m", provider="p", files_written=[str(new_file)])
        manager.on_turn_callback(turn)

        commit_events = [e for e in emitter.events if e[0] == "AgentCommitCreated"]
        assert len(commit_events) == 1
        assert commit_events[0][1]["repo_name"] == "project"
        assert len(commit_events[0][1]["sha"]) == 40

    def test_emits_agent_turn_completed(self, manager: WorkspaceManager, git_repo: Path, emitter: RecordingEmitter) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        new_file = git_repo / "d.txt"
        new_file.write_text("d\n")

        turn = AgentTurn(turn_number=1, model="m", provider="p", files_written=[str(new_file)])
        manager.on_turn_callback(turn)

        turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
        assert len(turn_events) == 1
        assert turn_events[0][1]["git_sha"] != ""


class TestOnTurnWithoutWrites:
    def test_no_commit(self, manager: WorkspaceManager, git_repo: Path) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        initial_sha = rev_parse("HEAD", cwd=git_repo)

        turn = AgentTurn(turn_number=1, model="m", provider="p", files_written=[])
        manager.on_turn_callback(turn)

        assert rev_parse("HEAD", cwd=git_repo) == initial_sha
        assert turn.git_sha == ""

    def test_still_emits_agent_turn_completed(self, manager: WorkspaceManager, git_repo: Path, emitter: RecordingEmitter) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        turn = AgentTurn(turn_number=1, model="m", provider="p")
        manager.on_turn_callback(turn)

        turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
        assert len(turn_events) == 1
        assert turn_events[0][1]["git_sha"] == ""


class TestNodeTracking:
    def test_tracks_stage_started(self, manager: WorkspaceManager, git_repo: Path) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="writer", handler_type="box"))

        new_file = git_repo / "e.txt"
        new_file.write_text("e\n")

        turn = AgentTurn(turn_number=1, model="m", provider="p", files_written=[str(new_file)])
        manager.on_turn_callback(turn)

        commit_body = log(1, fmt="%B", cwd=git_repo)
        assert "Orchestra-Node: writer" in commit_body

    def test_clears_on_stage_completed(self, manager: WorkspaceManager, git_repo: Path) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="writer", handler_type="box"))
        manager.on_event(StageCompleted(node_id="writer", handler_type="box"))

        new_file = git_repo / "f.txt"
        new_file.write_text("f\n")

        turn = AgentTurn(turn_number=1, model="m", provider="p", files_written=[str(new_file)])
        manager.on_turn_callback(turn)

        commit_body = log(1, fmt="%B", cwd=git_repo)
        assert "Orchestra-Node: unknown" in commit_body


class TestHasWorkspace:
    def test_with_repos(self, manager: WorkspaceManager) -> None:
        assert manager.has_workspace is True

    def test_without_repos(self, emitter: RecordingEmitter, commit_gen: DeterministicCommitMessageGenerator) -> None:
        config = OrchestraConfig()
        mgr = WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)
        assert mgr.has_workspace is False


class TestMultipleTurns:
    def test_three_turns_three_commits(self, manager: WorkspaceManager, git_repo: Path) -> None:
        manager.setup_session("pipe", "sess1")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        shas = []
        for i in range(3):
            f = git_repo / f"file_{i}.py"
            f.write_text(f"content {i}\n")
            turn = AgentTurn(
                turn_number=i + 1,
                model="m",
                provider="p",
                files_written=[str(f)],
            )
            manager.on_turn_callback(turn)
            shas.append(turn.git_sha)

        assert len(set(shas)) == 3
        for sha in shas:
            assert len(sha) == 40
