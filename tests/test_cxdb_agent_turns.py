"""Integration tests for AgentTurn CXDB recording via events."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
from orchestra.events.types import StageStarted
from orchestra.models.agent_turn import AgentTurn
from orchestra.workspace.commit_message import DeterministicCommitMessageGenerator
from orchestra.workspace.git_ops import run_git
from orchestra.workspace.on_turn import build_on_turn_callback
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


class TestAgentTurnWithWritesHasSHA:
    def test_sha_populated(self, git_repo: Path) -> None:
        config = OrchestraConfig(
            workspace=WorkspaceConfig(repos={"project": RepoConfig(path=str(git_repo))}),
            config_dir=git_repo.parent,
        )
        emitter = RecordingEmitter()
        manager = WorkspaceManager(
            config=config, event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )
        manager.setup_session("pipe", "sess")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        f = git_repo / "a.py"
        f.write_text("a\n")
        turn = AgentTurn(turn_number=1, model="m", provider="p", files_written=[str(f)])
        manager.on_turn_callback(turn)

        turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
        assert len(turn_events) == 1
        assert turn_events[0][1]["git_sha"] != ""
        assert len(turn_events[0][1]["git_sha"]) == 40


class TestAgentTurnWithoutWritesEmptySHA:
    def test_empty_sha(self, git_repo: Path) -> None:
        config = OrchestraConfig(
            workspace=WorkspaceConfig(repos={"project": RepoConfig(path=str(git_repo))}),
            config_dir=git_repo.parent,
        )
        emitter = RecordingEmitter()
        manager = WorkspaceManager(
            config=config, event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )
        manager.setup_session("pipe", "sess")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        turn = AgentTurn(turn_number=1, model="m", provider="p")
        manager.on_turn_callback(turn)

        turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
        assert len(turn_events) == 1
        assert turn_events[0][1]["git_sha"] == ""


class TestAgentTurnCompletedAlwaysEmitted:
    def test_emitted_with_workspace(self, git_repo: Path) -> None:
        config = OrchestraConfig(
            workspace=WorkspaceConfig(repos={"project": RepoConfig(path=str(git_repo))}),
            config_dir=git_repo.parent,
        )
        emitter = RecordingEmitter()
        manager = WorkspaceManager(
            config=config, event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )
        manager.setup_session("pipe", "sess")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        turn = AgentTurn(turn_number=1, model="m", provider="p")
        manager.on_turn_callback(turn)

        turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
        assert len(turn_events) == 1

    def test_emitted_without_workspace(self) -> None:
        emitter = RecordingEmitter()
        callback = build_on_turn_callback(emitter, workspace_manager=None)

        turn = AgentTurn(turn_number=1, model="m", provider="p")
        callback(turn)

        turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
        assert len(turn_events) == 1
        assert turn_events[0][1]["turn_number"] == 1
        assert turn_events[0][1]["model"] == "m"


class TestBidirectionalCorrelation:
    def test_sha_matches_git_commit(self, git_repo: Path) -> None:
        config = OrchestraConfig(
            workspace=WorkspaceConfig(repos={"project": RepoConfig(path=str(git_repo))}),
            config_dir=git_repo.parent,
        )
        emitter = RecordingEmitter()
        manager = WorkspaceManager(
            config=config, event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )
        manager.setup_session("pipe", "sess")
        manager.on_event(StageStarted(node_id="code", handler_type="box"))

        f = git_repo / "b.py"
        f.write_text("b\n")
        turn = AgentTurn(turn_number=1, model="m", provider="p", files_written=[str(f)])
        manager.on_turn_callback(turn)

        # Get SHA from event
        turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
        event_sha = turn_events[0][1]["git_sha"]

        # Get SHA from git log
        from orchestra.workspace.git_ops import log as git_log
        git_sha = git_log(1, fmt="%H", cwd=git_repo)

        assert event_sha == git_sha

    def test_trailers_identify_session(self, git_repo: Path) -> None:
        config = OrchestraConfig(
            workspace=WorkspaceConfig(repos={"project": RepoConfig(path=str(git_repo))}),
            config_dir=git_repo.parent,
        )
        emitter = RecordingEmitter()
        manager = WorkspaceManager(
            config=config, event_emitter=emitter,
            commit_gen=DeterministicCommitMessageGenerator(),
        )
        manager.setup_session("my-pipe", "sess-42")
        manager.on_event(StageStarted(node_id="coder", handler_type="box"))

        f = git_repo / "c.py"
        f.write_text("c\n")
        turn = AgentTurn(turn_number=3, model="gpt-4o", provider="openai", files_written=[str(f)])
        manager.on_turn_callback(turn)

        from orchestra.workspace.git_ops import log as git_log
        body = git_log(1, fmt="%B", cwd=git_repo)

        assert "Orchestra-Session: sess-42" in body
        assert "Orchestra-Turn: 3" in body
        assert "Orchestra-Node: coder" in body
