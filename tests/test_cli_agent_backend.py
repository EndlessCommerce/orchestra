import json
from unittest.mock import MagicMock, patch

from orchestra.backends.cli_agent import CLIAgentBackend
from orchestra.models.context import Context
from orchestra.models.graph import Node
from orchestra.models.outcome import Outcome, OutcomeStatus


def _make_node() -> Node:
    return Node(id="test", label="test", shape="box", prompt="Do work", attributes={})


class TestCLIAgentBackend:
    def test_mock_subprocess_returns_stdout(self):
        backend = CLIAgentBackend(command="echo", args=["hello"])
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Agent output\n",
                stderr="",
            )
            result = backend.run(_make_node(), "prompt", Context())
        assert result == "Agent output\n"

    def test_does_not_invoke_on_turn(self):
        backend = CLIAgentBackend(command="echo")
        turns: list = []
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            backend.run(
                _make_node(),
                "prompt",
                Context(),
                on_turn=lambda t: turns.append(t),
            )
        assert turns == []

    def test_context_file_written(self):
        backend = CLIAgentBackend(command="echo")
        ctx = Context()
        ctx.set("key", "value")

        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            backend.run(_make_node(), "prompt", ctx)

            call_kwargs = mock_run.call_args
            env = call_kwargs.kwargs.get("env", {})
            assert "ORCHESTRA_CONTEXT_FILE" in env

    def test_subprocess_error_returns_fail(self):
        backend = CLIAgentBackend(command="echo")
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Error: something went wrong",
            )
            result = backend.run(_make_node(), "prompt", Context())
        assert isinstance(result, Outcome)
        assert result.status == OutcomeStatus.FAIL
        assert "something went wrong" in result.failure_reason

    def test_command_not_found_returns_fail(self):
        backend = CLIAgentBackend(command="nonexistent_command_xyz")
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("not found")
            result = backend.run(_make_node(), "prompt", Context())
        assert isinstance(result, Outcome)
        assert result.status == OutcomeStatus.FAIL
        assert "not found" in result.failure_reason

    def test_prompt_passed_via_stdin(self):
        backend = CLIAgentBackend(command="cat")
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            backend.run(_make_node(), "my prompt text", Context())
            call_kwargs = mock_run.call_args
            assert call_kwargs.kwargs.get("input") == "my prompt text"

    def test_accepts_on_turn_none(self):
        backend = CLIAgentBackend(command="echo")
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            result = backend.run(_make_node(), "prompt", Context(), on_turn=None)
        assert result == "ok"
