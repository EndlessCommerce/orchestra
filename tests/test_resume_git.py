"""Tests for resume with git state restoration.

Tests cover:
- restore_git_state checkouts repos to specified SHAs
- restore_from_turn extracts git_sha and reconstructs prior messages
- Fallback to most recent prior SHA when AgentTurn has empty git_sha
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from orchestra.config.settings import RepoConfig
from orchestra.engine.turn_resume import TurnResumeInfo, restore_from_turn
from orchestra.workspace.restore import restore_git_state


# ---------------------------------------------------------------------------
# Helpers for creating temporary git repos
# ---------------------------------------------------------------------------


def _init_git_repo(repo_path: Path) -> str:
    """Initialise a git repo with an initial commit and return its SHA."""
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "README.md").write_text("initial\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    return _head_sha(repo_path)


def _make_commit(repo_path: Path, filename: str, content: str, message: str) -> str:
    """Create a new commit and return its SHA."""
    (repo_path / filename).write_text(content)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    return _head_sha(repo_path)


def _head_sha(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Helpers for building mock CXDB turn lists
# ---------------------------------------------------------------------------


def _pipeline_started_turn(
    pipeline_name: str = "test_pipeline",
    dot_file_path: str = "/tmp/test.dot",
    graph_hash: str = "deadbeef",
) -> dict[str, Any]:
    return {
        "turn_id": "t-start",
        "type_id": "dev.orchestra.PipelineLifecycle",
        "data": {
            "pipeline_name": pipeline_name,
            "status": "started",
            "session_display_id": "sess-1",
            "dot_file_path": dot_file_path,
            "graph_hash": graph_hash,
        },
    }


def _checkpoint_turn(
    turn_id: str = "t-cp",
    current_node: str = "start",
    completed_nodes: list[str] | None = None,
    next_node_id: str = "plan",
    visited_outcomes: dict[str, str] | None = None,
    workspace_snapshot: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "type_id": "dev.orchestra.Checkpoint",
        "data": {
            "current_node": current_node,
            "completed_nodes": completed_nodes or ["start"],
            "context_snapshot": {},
            "next_node_id": next_node_id,
            "visited_outcomes": visited_outcomes or {"start": "SUCCESS"},
            "reroute_count": 0,
            "workspace_snapshot": workspace_snapshot or {},
        },
    }


def _agent_turn(
    turn_id: str,
    turn_number: int,
    node_id: str,
    git_sha: str = "",
    messages: list[dict[str, Any]] | None = None,
    model: str = "test-model",
) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "type_id": "dev.orchestra.AgentTurn",
        "data": {
            "turn_number": turn_number,
            "node_id": node_id,
            "model": model,
            "git_sha": git_sha,
            "messages": json.dumps(messages or []),
        },
    }


# ===========================================================================
# Test: restore_git_state — single repo
# ===========================================================================


class TestRestoreGitStateSingleRepo:
    def test_resume_at_node_boundary(self, tmp_path: Path) -> None:
        """restore_git_state checks out a repo to the specified SHA."""
        repo_path = tmp_path / "project"
        initial_sha = _init_git_repo(repo_path)

        # Create extra commits so HEAD moves ahead
        _make_commit(repo_path, "a.txt", "aaa", "second commit")
        third_sha = _make_commit(repo_path, "b.txt", "bbb", "third commit")

        # HEAD is now at third commit
        assert _head_sha(repo_path) == third_sha

        # Build config pointing to the repo
        repos = {
            "project": RepoConfig(path=str(repo_path)),
        }
        snapshot = {"project": initial_sha}

        # Restore to the initial commit
        restore_git_state(snapshot, repos, config_dir=tmp_path)

        # HEAD should now be at the initial commit
        assert _head_sha(repo_path) == initial_sha


# ===========================================================================
# Test: restore_git_state — multiple repos
# ===========================================================================


class TestRestoreGitStateMultipleRepos:
    def test_resume_at_node_restores_multiple_repos(self, tmp_path: Path) -> None:
        """Both repos are restored to the correct SHAs from the snapshot."""
        # Set up repo A
        repo_a_path = tmp_path / "repo-a"
        initial_a = _init_git_repo(repo_a_path)
        _make_commit(repo_a_path, "extra.txt", "extra", "advance A")

        # Set up repo B
        repo_b_path = tmp_path / "repo-b"
        initial_b = _init_git_repo(repo_b_path)
        _make_commit(repo_b_path, "extra.txt", "extra", "advance B")

        # Both repos are now ahead of their initial commits
        assert _head_sha(repo_a_path) != initial_a
        assert _head_sha(repo_b_path) != initial_b

        repos = {
            "backend": RepoConfig(path=str(repo_a_path)),
            "frontend": RepoConfig(path=str(repo_b_path)),
        }
        snapshot = {
            "backend": initial_a,
            "frontend": initial_b,
        }

        restore_git_state(snapshot, repos, config_dir=tmp_path)

        assert _head_sha(repo_a_path) == initial_a
        assert _head_sha(repo_b_path) == initial_b


# ===========================================================================
# Test: restore_from_turn — basic AgentTurn lookup
# ===========================================================================


class TestRestoreFromTurn:
    def test_resume_at_agent_turn(self) -> None:
        """restore_from_turn finds the target turn and extracts git_sha."""
        turns = [
            _pipeline_started_turn(),
            _checkpoint_turn(
                turn_id="t-cp1",
                current_node="start",
                completed_nodes=["start"],
                next_node_id="plan",
                visited_outcomes={"start": "SUCCESS"},
                workspace_snapshot={"project": "abc123"},
            ),
            _agent_turn(
                turn_id="t-agent-1",
                turn_number=1,
                node_id="plan",
                git_sha="abc123",
                messages=[{"role": "user", "content": "Plan the work"}],
            ),
        ]

        info = restore_from_turn(turns, turn_id="t-agent-1", context_id="ctx-1")

        assert isinstance(info, TurnResumeInfo)
        assert info.turn_number == 1
        assert info.next_node_id == "plan"
        assert info.git_sha == "abc123"
        assert info.context_id == "ctx-1"
        assert info.pipeline_name == "test_pipeline"
        assert info.dot_file_path == "/tmp/test.dot"
        assert info.graph_hash == "deadbeef"

    # -----------------------------------------------------------------------
    # Test: prior_messages reconstructed from prior AgentTurns
    # -----------------------------------------------------------------------

    def test_resume_at_agent_turn_restores_agent_state(self) -> None:
        """Prior messages are reconstructed from all AgentTurns for the same node."""
        turns = [
            _pipeline_started_turn(),
            _checkpoint_turn(
                turn_id="t-cp1",
                current_node="start",
                completed_nodes=["start"],
                next_node_id="plan",
            ),
            # First agent turn on "plan"
            _agent_turn(
                turn_id="t-agent-1",
                turn_number=1,
                node_id="plan",
                git_sha="sha-1",
                messages=[
                    {"role": "user", "content": "Plan the work"},
                    {"role": "assistant", "content": "Here is the plan"},
                ],
            ),
            # Second agent turn on "plan"
            _agent_turn(
                turn_id="t-agent-2",
                turn_number=2,
                node_id="plan",
                git_sha="sha-2",
                messages=[
                    {"role": "user", "content": "Refine the plan"},
                    {"role": "assistant", "content": "Refined plan"},
                ],
            ),
            # Third agent turn on "plan" — this is our target
            _agent_turn(
                turn_id="t-agent-3",
                turn_number=3,
                node_id="plan",
                git_sha="sha-3",
                messages=[
                    {"role": "user", "content": "Final review"},
                    {"role": "assistant", "content": "Looks good"},
                ],
            ),
        ]

        info = restore_from_turn(turns, turn_id="t-agent-3", context_id="ctx-1")

        # prior_messages should contain messages from all three turns (turns 1-3)
        assert len(info.prior_messages) == 6
        assert info.prior_messages[0]["content"] == "Plan the work"
        assert info.prior_messages[1]["content"] == "Here is the plan"
        assert info.prior_messages[2]["content"] == "Refine the plan"
        assert info.prior_messages[3]["content"] == "Refined plan"
        assert info.prior_messages[4]["content"] == "Final review"
        assert info.prior_messages[5]["content"] == "Looks good"

        # git_sha should come from the target turn itself
        assert info.git_sha == "sha-3"
        assert info.turn_number == 3

    # -----------------------------------------------------------------------
    # Test: AgentTurns for a *different* node are excluded from prior_messages
    # -----------------------------------------------------------------------

    def test_prior_messages_scoped_to_target_node(self) -> None:
        """Messages from a different node are not included in prior_messages."""
        turns = [
            _pipeline_started_turn(),
            _checkpoint_turn(
                turn_id="t-cp1",
                current_node="start",
                completed_nodes=["start"],
                next_node_id="plan",
            ),
            # Turn on a different node ("code")
            _agent_turn(
                turn_id="t-agent-0",
                turn_number=1,
                node_id="code",
                git_sha="other-sha",
                messages=[{"role": "user", "content": "Write code"}],
            ),
            # Turn on "plan" — our target
            _agent_turn(
                turn_id="t-agent-1",
                turn_number=2,
                node_id="plan",
                git_sha="plan-sha",
                messages=[{"role": "user", "content": "Plan it"}],
            ),
        ]

        info = restore_from_turn(turns, turn_id="t-agent-1", context_id="ctx-1")

        # Only the "plan" turn's messages should be present
        assert len(info.prior_messages) == 1
        assert info.prior_messages[0]["content"] == "Plan it"

    # -----------------------------------------------------------------------
    # Test: Empty git_sha falls back to most recent prior SHA
    # -----------------------------------------------------------------------

    def test_resume_at_read_only_turn(self) -> None:
        """AgentTurn with empty git_sha falls back to the most recent prior SHA."""
        turns = [
            _pipeline_started_turn(),
            _checkpoint_turn(
                turn_id="t-cp1",
                current_node="start",
                completed_nodes=["start"],
                next_node_id="plan",
            ),
            # Prior turn with a git_sha
            _agent_turn(
                turn_id="t-agent-1",
                turn_number=1,
                node_id="plan",
                git_sha="prior-sha-abc",
                messages=[{"role": "user", "content": "Do something"}],
            ),
            # Target turn with empty git_sha (read-only, no commit was made)
            _agent_turn(
                turn_id="t-agent-2",
                turn_number=2,
                node_id="plan",
                git_sha="",
                messages=[{"role": "user", "content": "Read-only turn"}],
            ),
        ]

        info = restore_from_turn(turns, turn_id="t-agent-2", context_id="ctx-1")

        # Should fall back to the prior turn's SHA
        assert info.git_sha == "prior-sha-abc"
        assert info.turn_number == 2

    def test_resume_at_read_only_turn_no_prior_sha(self) -> None:
        """AgentTurn with empty git_sha and no prior SHA results in empty git_sha."""
        turns = [
            _pipeline_started_turn(),
            _checkpoint_turn(
                turn_id="t-cp1",
                current_node="start",
                completed_nodes=["start"],
                next_node_id="plan",
            ),
            # Target turn with empty git_sha and no prior AgentTurns with a SHA
            _agent_turn(
                turn_id="t-agent-1",
                turn_number=1,
                node_id="plan",
                git_sha="",
                messages=[{"role": "user", "content": "First turn, no prior SHA"}],
            ),
        ]

        info = restore_from_turn(turns, turn_id="t-agent-1", context_id="ctx-1")

        # No prior SHA to fall back to — should remain empty
        assert info.git_sha == ""


# ===========================================================================
# Test: restore_git_state edge cases
# ===========================================================================


class TestRestoreGitStateEdgeCases:
    def test_already_at_target_sha(self, tmp_path: Path) -> None:
        """If repo is already at the target SHA, restore is a no-op."""
        repo_path = tmp_path / "project"
        initial_sha = _init_git_repo(repo_path)

        repos = {"project": RepoConfig(path=str(repo_path))}
        snapshot = {"project": initial_sha}

        # HEAD is already at initial_sha — this should succeed without error
        restore_git_state(snapshot, repos, config_dir=tmp_path)
        assert _head_sha(repo_path) == initial_sha

    def test_snapshot_repo_not_in_config(self, tmp_path: Path) -> None:
        """Repo in snapshot but not in config is skipped without error."""
        repo_path = tmp_path / "project"
        initial_sha = _init_git_repo(repo_path)

        repos = {"project": RepoConfig(path=str(repo_path))}
        # Snapshot references a repo that is not in the repos config
        snapshot = {"project": initial_sha, "unknown_repo": "deadbeef"}

        # Should not raise — unknown_repo is skipped
        restore_git_state(snapshot, repos, config_dir=tmp_path)
        assert _head_sha(repo_path) == initial_sha

    def test_relative_path_resolved_from_config_dir(self, tmp_path: Path) -> None:
        """Relative repo path is resolved relative to config_dir."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        repo_path = tmp_path / "config" / "project"
        initial_sha = _init_git_repo(repo_path)
        _make_commit(repo_path, "extra.txt", "data", "advance")

        repos = {"project": RepoConfig(path="project")}
        snapshot = {"project": initial_sha}

        restore_git_state(snapshot, repos, config_dir=config_dir)
        assert _head_sha(repo_path) == initial_sha
