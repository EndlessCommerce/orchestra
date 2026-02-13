"""Integration tests for per-turn commits via WorkspaceManager."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
from orchestra.events.types import StageStarted
from orchestra.models.agent_turn import AgentTurn
from orchestra.workspace.commit_message import DeterministicCommitMessageGenerator
from orchestra.workspace.git_ops import current_branch, log, rev_parse, run_git, status
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
    (repo / "README.md").write_text("# Project\n")
    run_git("add", "README.md", cwd=repo)
    run_git("commit", "-m", "Initial commit", cwd=repo)
    return repo


def _make_manager(git_repo: Path) -> tuple[WorkspaceManager, RecordingEmitter]:
    config = OrchestraConfig(
        workspace=WorkspaceConfig(repos={"project": RepoConfig(path=str(git_repo))}),
        config_dir=git_repo.parent,
    )
    emitter = RecordingEmitter()
    commit_gen = DeterministicCommitMessageGenerator()
    manager = WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)
    return manager, emitter


class TestPerTurnCommitExactFiles:
    def test_only_written_files_staged(self, git_repo: Path) -> None:
        manager, _ = _make_manager(git_repo)
        manager.setup_session("pipe", "sess")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        # Create a dirty file that should NOT be committed
        (git_repo / "untracked.txt").write_text("dirty\n")

        # Agent writes only one file
        written_file = git_repo / "agent_output.py"
        written_file.write_text("print('hello')\n")

        turn = AgentTurn(
            turn_number=1, model="m", provider="p",
            files_written=[str(written_file)],
        )
        manager.on_turn_callback(turn)

        # Verify: agent_output.py is committed, untracked.txt is not
        git_status = status(cwd=git_repo)
        assert "untracked.txt" in git_status  # still untracked
        assert "agent_output.py" not in git_status  # committed

    def test_turn_without_writes_no_commit(self, git_repo: Path) -> None:
        manager, _ = _make_manager(git_repo)
        manager.setup_session("pipe", "sess")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        initial_sha = rev_parse("HEAD", cwd=git_repo)

        turn = AgentTurn(turn_number=1, model="m", provider="p", files_written=[])
        manager.on_turn_callback(turn)

        assert rev_parse("HEAD", cwd=git_repo) == initial_sha


class TestMultipleTurnCommits:
    def test_three_turns_three_commits(self, git_repo: Path) -> None:
        manager, _ = _make_manager(git_repo)
        manager.setup_session("pipe", "sess")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        shas = []
        for i in range(3):
            f = git_repo / f"file_{i}.py"
            f.write_text(f"content_{i}\n")
            turn = AgentTurn(
                turn_number=i + 1, model="m", provider="p",
                files_written=[str(f)],
            )
            manager.on_turn_callback(turn)
            shas.append(turn.git_sha)

        # All distinct SHAs
        assert len(set(shas)) == 3

        # Git log shows 3 + 1 (initial) commits
        log_output = log(4, fmt="%s", cwd=git_repo)
        assert log_output.count("chore: auto-commit") == 3


class TestCommitAuthor:
    def test_author_format(self, git_repo: Path) -> None:
        manager, _ = _make_manager(git_repo)
        manager.setup_session("pipe", "sess")
        manager.on_event(StageStarted(node_id="writer", handler_type="box"))

        f = git_repo / "test.py"
        f.write_text("test\n")
        turn = AgentTurn(
            turn_number=1, model="claude-3.5-sonnet", provider="anthropic",
            files_written=[str(f)],
        )
        manager.on_turn_callback(turn)

        author = log(1, fmt="%an <%ae>", cwd=git_repo)
        assert "writer (claude-3.5-sonnet)" in author
        assert "orchestra@local" in author


class TestCommitTrailers:
    def test_all_six_trailers(self, git_repo: Path) -> None:
        manager, _ = _make_manager(git_repo)
        manager.setup_session("my-pipeline", "abc123")
        manager.on_event(StageStarted(node_id="coder", handler_type="box"))

        f = git_repo / "x.py"
        f.write_text("x\n")
        turn = AgentTurn(
            turn_number=5, model="gpt-4o", provider="openai",
            files_written=[str(f)],
        )
        manager.on_turn_callback(turn)

        body = log(1, fmt="%B", cwd=git_repo)
        assert "Orchestra-Model: gpt-4o" in body
        assert "Orchestra-Provider: openai" in body
        assert "Orchestra-Node: coder" in body
        assert "Orchestra-Pipeline: my-pipeline" in body
        assert "Orchestra-Session: abc123" in body
        assert "Orchestra-Turn: 5" in body


class TestCommitMessageByMockLLM:
    def test_deterministic_message_format(self, git_repo: Path) -> None:
        manager, _ = _make_manager(git_repo)
        manager.setup_session("pipe", "sess")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        f = git_repo / "hello.py"
        f.write_text("print('hello')\n")
        turn = AgentTurn(
            turn_number=1, model="m", provider="p",
            files_written=[str(f)],
        )
        manager.on_turn_callback(turn)

        assert turn.commit_message.startswith("chore: auto-commit")
