import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from orchestra.engine.runner import PipelineRunner
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.registry import HandlerRegistry
from orchestra.handlers.start import StartHandler
from orchestra.handlers.tool_handler import ToolHandler
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


def _make_node(tool_command: str | None = None, timeout: str = "60s", **extra) -> Node:
    attrs: dict = {}
    if tool_command is not None:
        attrs["tool_command"] = tool_command
    if timeout != "60s":
        attrs["timeout"] = timeout
    attrs.update(extra)
    return Node(id="tool_node", label="tool_node", shape="parallelogram", attributes=attrs)


def _make_graph() -> PipelineGraph:
    return PipelineGraph(name="test", nodes={}, edges=[], graph_attributes={})


class TestToolHandler:
    def test_execute_echo_command(self):
        handler = ToolHandler()
        node = _make_node(tool_command="echo hello")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.context_updates["tool.output"] == "hello"
        assert outcome.context_updates["tool.exit_code"] == 0

    def test_command_failure(self):
        handler = ToolHandler()
        node = _make_node(tool_command="false")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.FAIL
        assert "exited with code" in outcome.failure_reason

    def test_command_timeout(self):
        handler = ToolHandler()
        node = _make_node(tool_command="sleep 10", timeout="0.1s")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.FAIL
        assert "timed out" in outcome.failure_reason

    def test_output_in_context(self):
        handler = ToolHandler()
        node = _make_node(tool_command="echo 'test output'")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.context_updates["tool.output"] == "test output"

    def test_no_command_specified(self):
        handler = ToolHandler()
        node = _make_node()  # No tool_command
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.FAIL
        assert outcome.failure_reason == "No tool_command specified"

    def test_workspace_cwd_scoping(self, tmp_path):
        # Create a mock workspace manager with a repo
        workspace_mgr = MagicMock()
        workspace_mgr.has_workspace = True

        repo_ctx = MagicMock()
        repo_ctx.path = tmp_path
        workspace_mgr._repo_contexts = {"test-repo": repo_ctx}

        handler = ToolHandler(workspace_manager=workspace_mgr)
        # Use pwd to verify we're in the right directory
        node = _make_node(tool_command="pwd")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.context_updates["tool.output"] == str(tmp_path)

    def test_multiline_output(self):
        handler = ToolHandler()
        node = _make_node(tool_command="echo 'line1\nline2\nline3'")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.SUCCESS
        assert "line1" in outcome.context_updates["tool.output"]

    def test_duration_tracked(self):
        handler = ToolHandler()
        node = _make_node(tool_command="echo fast")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.SUCCESS
        assert "tool.duration_ms" in outcome.context_updates
        assert isinstance(outcome.context_updates["tool.duration_ms"], int)

    def test_parse_timeout_seconds(self):
        assert ToolHandler._parse_timeout("30s") == 30.0

    def test_parse_timeout_minutes(self):
        assert ToolHandler._parse_timeout("5m") == 300.0

    def test_parse_timeout_plain_number(self):
        assert ToolHandler._parse_timeout("60") == 60.0

    def test_pipe_command(self):
        handler = ToolHandler()
        node = _make_node(tool_command="echo 'hello world' | tr ' ' '_'")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.context_updates["tool.output"] == "hello_world"

    def test_no_workspace_uses_default_cwd(self):
        handler = ToolHandler()
        node = _make_node(tool_command="pwd")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.status == OutcomeStatus.SUCCESS
        # Should run in current directory (no workspace scoping)
        assert len(outcome.context_updates["tool.output"]) > 0


class _RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


class TestCustomHandlerRegistration:
    """Test that custom handlers can be registered and dispatched."""

    def test_custom_handler_dispatched(self):
        """Register custom handler for a custom shape → pipeline dispatches to it."""

        class CustomHandler:
            def __init__(self) -> None:
                self.called_nodes: list[str] = []

            def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
                self.called_nodes.append(node.id)
                return Outcome(status=OutcomeStatus.SUCCESS)

        graph = PipelineGraph(
            name="custom_handler_test",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "custom": Node(id="custom", shape="custom_shape", prompt="Custom task"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="custom"),
                Edge(from_node="custom", to_node="exit"),
            ],
        )

        emitter = _RecordingEmitter()
        custom = CustomHandler()

        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("custom_shape", custom)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS
        assert "custom" in custom.called_nodes

        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "custom" in completed

    def test_custom_handler_with_context_updates(self):
        """Custom handler can update context and downstream nodes see it."""

        class ContextSettingHandler:
            def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
                return Outcome(
                    status=OutcomeStatus.SUCCESS,
                    context_updates={"custom_key": "custom_value"},
                )

        class ContextReadingHandler:
            def __init__(self) -> None:
                self.seen_context: dict[str, Any] = {}

            def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
                self.seen_context = dict(context.snapshot())
                return Outcome(status=OutcomeStatus.SUCCESS)

        graph = PipelineGraph(
            name="custom_context_test",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "setter": Node(id="setter", shape="custom_shape", prompt="Set"),
                "reader": Node(id="reader", shape="reader_shape", prompt="Read"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="setter"),
                Edge(from_node="setter", to_node="reader"),
                Edge(from_node="reader", to_node="exit"),
            ],
        )

        emitter = _RecordingEmitter()
        reader = ContextReadingHandler()

        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("custom_shape", ContextSettingHandler())
        registry.register("reader_shape", reader)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS
        assert reader.seen_context.get("custom_key") == "custom_value"
