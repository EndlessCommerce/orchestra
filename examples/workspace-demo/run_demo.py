#!/usr/bin/env python3
"""Workspace Demo — Stage 6a

Demonstrates workspace configuration, session branches, and per-turn commits
without requiring LLM API keys. Uses WorkspaceManager directly to simulate
what happens during a real pipeline run.

Usage:
    python run_demo.py
    python run_demo.py --keep-temp   # preserve temp directory for inspection
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
from orchestra.events.types import StageStarted
from orchestra.models.agent_turn import AgentTurn
from orchestra.workspace.commit_message import DeterministicCommitMessageGenerator
from orchestra.workspace.git_ops import current_branch, log, rev_parse, run_git
from orchestra.workspace.on_turn import build_on_turn_callback
from orchestra.workspace.workspace_manager import WorkspaceManager

SAMPLE_PROJECT = Path(__file__).resolve().parent / "sample-project"

SEPARATOR = "=" * 60


class DemoEmitter:
    """Records events and prints them as they arrive."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


# ── helpers ─────────────────────────────────────────────────────


def _init_repo(path: Path) -> Path:
    """Copy sample-project into *path* and initialise it as a git repo."""
    shutil.copytree(SAMPLE_PROJECT, path)
    run_git("init", cwd=path)
    run_git("config", "user.email", "demo@example.com", cwd=path)
    run_git("config", "user.name", "Demo User", cwd=path)
    run_git("add", ".", cwd=path)
    run_git("commit", "-m", "Initial commit: calculator project", cwd=path)
    return path


def _print(label: str, value: str = "") -> None:
    if value:
        print(f"  {label}: {value}")
    else:
        print(f"  {label}")


# ── main demo ───────────────────────────────────────────────────


def main() -> None:
    keep_temp = "--keep-temp" in sys.argv
    tmp = Path(tempfile.mkdtemp(prefix="orchestra-workspace-demo-"))

    print(SEPARATOR)
    print("  Stage 6a Workspace Demo")
    print(SEPARATOR)
    print()

    try:
        _run_demo(tmp)
    finally:
        if keep_temp:
            print(f"Temp directory preserved: {tmp}")
            print("Inspect with:")
            print(f"  cd {tmp / 'project'}")
            print(f"  git log --all --oneline --graph")
        else:
            shutil.rmtree(tmp)
            print("Temp directory cleaned up.")


def _run_demo(tmp: Path) -> None:
    # ── 1. Set up a sample git repo ─────────────────────────────
    repo = _init_repo(tmp / "project")
    original_branch = current_branch(cwd=repo)
    original_sha = rev_parse("HEAD", cwd=repo)

    print(f"Sample repo: {repo}")
    _print("Branch", original_branch)
    _print("HEAD", original_sha[:12])
    print()

    # ── 2. Configure workspace ──────────────────────────────────
    config = OrchestraConfig(
        workspace=WorkspaceConfig(
            repos={"project": RepoConfig(path=str(repo))},
        ),
        config_dir=tmp,
    )
    emitter = DemoEmitter()
    manager = WorkspaceManager(
        config=config,
        event_emitter=emitter,
        commit_gen=DeterministicCommitMessageGenerator(),
    )

    # ── 3. Setup session — creates branch ───────────────────────
    print("--- 1. Setup Session ---")
    contexts = manager.setup_session("add-tests", "demo-001")
    session_branch = contexts["project"].branch
    _print("Session branch created", session_branch)
    _print("Current branch", current_branch(cwd=repo))
    print()

    # ── 4. Build on_turn callback (same as cli/run.py) ──────────
    on_turn = build_on_turn_callback(emitter, workspace_manager=manager)

    # ── 5. Simulate agent turns ─────────────────────────────────
    # Tell the manager which node is running (normally done by EventDispatcher)
    manager.on_event(StageStarted(node_id="write_tests", handler_type="box"))

    # Turn 1: Agent writes test file
    print("--- 2. Agent Turn 1: Write Tests ---")
    test_file = repo / "test_calculator.py"
    test_file.write_text(
        'import pytest\n'
        'from calculator import Calculator\n'
        '\n'
        '\n'
        'class TestCalculator:\n'
        '    def setup_method(self):\n'
        '        self.calc = Calculator()\n'
        '\n'
        '    def test_add(self):\n'
        '        assert self.calc.add(2, 3) == 5\n'
        '\n'
        '    def test_subtract(self):\n'
        '        assert self.calc.subtract(10, 4) == 6\n'
        '\n'
        '    def test_multiply(self):\n'
        '        assert self.calc.multiply(3, 4) == 12\n'
        '\n'
        '    def test_divide(self):\n'
        '        assert self.calc.divide(10, 2) == 5.0\n'
        '\n'
        '    def test_divide_by_zero(self):\n'
        '        with pytest.raises(ValueError):\n'
        '            self.calc.divide(1, 0)\n'
    )
    turn1 = AgentTurn(
        turn_number=1,
        model="claude-sonnet-4-20250514",
        provider="anthropic",
        files_written=[str(test_file)],
    )
    on_turn(turn1)
    _print("Committed", f"{turn1.git_sha[:12]}  {turn1.commit_message.splitlines()[0]}")
    print()

    # Turn 2: Agent adds edge-case tests in a new file
    print("--- 3. Agent Turn 2: Edge-Case Tests ---")
    edge_file = repo / "test_calculator_edge.py"
    edge_file.write_text(
        'from calculator import Calculator\n'
        '\n'
        '\n'
        'def test_add_negative():\n'
        '    assert Calculator().add(-1, -2) == -3\n'
        '\n'
        '\n'
        'def test_add_zero():\n'
        '    assert Calculator().add(0, 0) == 0\n'
        '\n'
        '\n'
        'def test_multiply_by_zero():\n'
        '    assert Calculator().multiply(5, 0) == 0\n'
        '\n'
        '\n'
        'def test_large_numbers():\n'
        '    assert Calculator().add(10**18, 10**18) == 2 * 10**18\n'
    )
    turn2 = AgentTurn(
        turn_number=2,
        model="claude-sonnet-4-20250514",
        provider="anthropic",
        files_written=[str(edge_file)],
    )
    on_turn(turn2)
    _print("Committed", f"{turn2.git_sha[:12]}  {turn2.commit_message.splitlines()[0]}")
    print()

    # Turn 3: Read-only turn — no files written, no commit
    print("--- 4. Agent Turn 3: Read-Only (no commit) ---")
    turn3 = AgentTurn(
        turn_number=3,
        model="claude-sonnet-4-20250514",
        provider="anthropic",
        files_written=[],
    )
    on_turn(turn3)
    _print("SHA", turn3.git_sha or "(none — no files written)")
    print()

    # ── 6. Inspect git history ──────────────────────────────────
    print("--- 5. Git Log (session branch) ---")
    for line in log(10, fmt="%h %s", cwd=repo).strip().splitlines():
        _print(line)
    print()

    print("--- 6. Commit Trailers (most recent file commit) ---")
    body = log(1, fmt="%B", cwd=repo).strip()
    for line in body.splitlines():
        _print(line)
    author = log(1, fmt="%an <%ae>", cwd=repo).strip()
    _print("Author", author)
    print()

    # ── 7. Show events ──────────────────────────────────────────
    print("--- 7. Events Emitted ---")
    for etype, data in emitter.events:
        if etype == "SessionBranchCreated":
            _print(f"{etype}  repo={data['repo_name']}  branch={data['branch_name']}")
        elif etype == "AgentCommitCreated":
            _print(f"{etype}  sha={data['sha'][:12]}  node={data['node_id']}")
        elif etype == "AgentTurnCompleted":
            sha = data.get("git_sha", "")
            sha_display = sha[:12] + "..." if sha else "(empty)"
            _print(f"{etype}  turn={data['turn_number']}  sha={sha_display}")
    print()

    # ── 8. Teardown — restore original branch ───────────────────
    print("--- 8. Teardown Session ---")
    manager.teardown_session()
    _print("Current branch", f"{current_branch(cwd=repo)} (restored)")
    print()

    # ── 9. Verify ───────────────────────────────────────────────
    print("--- 9. Verification ---")
    checks_passed = 0

    assert current_branch(cwd=repo) == original_branch
    _print("[PASS] Original branch restored")
    checks_passed += 1

    assert rev_parse("HEAD", cwd=repo) == original_sha
    _print("[PASS] Original HEAD unchanged")
    checks_passed += 1

    branches = run_git("branch", "--list", cwd=repo)
    assert session_branch in branches
    _print("[PASS] Session branch preserved for inspection")
    checks_passed += 1

    assert len(turn1.git_sha) == 40 and len(turn2.git_sha) == 40
    assert turn1.git_sha != turn2.git_sha
    _print("[PASS] 2 distinct per-turn commits created")
    checks_passed += 1

    assert turn3.git_sha == ""
    _print("[PASS] Read-only turn produced no commit")
    checks_passed += 1

    turn_events = [e for e in emitter.events if e[0] == "AgentTurnCompleted"]
    assert len(turn_events) == 3
    _print("[PASS] AgentTurnCompleted emitted for all 3 turns")
    checks_passed += 1

    commit_events = [e for e in emitter.events if e[0] == "AgentCommitCreated"]
    assert len(commit_events) == 2
    _print("[PASS] AgentCommitCreated emitted for 2 commits")
    checks_passed += 1

    # Check trailers in the most recent session branch commit
    body = run_git("log", "-1", "--format=%B", session_branch, cwd=repo)
    for trailer in [
        "Orchestra-Model: claude-sonnet-4-20250514",
        "Orchestra-Provider: anthropic",
        "Orchestra-Node: write_tests",
        "Orchestra-Pipeline: add-tests",
        "Orchestra-Session: demo-001",
        "Orchestra-Turn: 2",
    ]:
        assert trailer in body, f"Missing trailer: {trailer}"
    _print("[PASS] All 6 git trailers present in commit")
    checks_passed += 1

    # Check author format
    author = run_git("log", "-1", "--format=%an <%ae>", session_branch, cwd=repo).strip()
    assert "write_tests" in author and "orchestra@local" in author
    _print("[PASS] Commit author identifies agent and model")
    checks_passed += 1

    # Check no-workspace callback still emits events
    plain_emitter = DemoEmitter()
    plain_callback = build_on_turn_callback(plain_emitter, workspace_manager=None)
    plain_turn = AgentTurn(turn_number=1, model="m", provider="p")
    plain_callback(plain_turn)
    plain_events = [e for e in plain_emitter.events if e[0] == "AgentTurnCompleted"]
    assert len(plain_events) == 1 and plain_events[0][1]["git_sha"] == ""
    _print("[PASS] No-workspace callback emits AgentTurnCompleted")
    checks_passed += 1

    print()
    print(f"All {checks_passed} checks passed.")
    print()


if __name__ == "__main__":
    main()
