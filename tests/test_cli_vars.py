import pytest
import typer

from orchestra.cli.run import _parse_vars
from orchestra.handlers.tool_handler import ToolHandler
from orchestra.models.context import Context
from orchestra.models.graph import PipelineGraph, Node


def _make_graph() -> PipelineGraph:
    return PipelineGraph(name="test", nodes={}, edges=[], graph_attributes={})


def _make_node(tool_command: str) -> Node:
    return Node(id="tool", label="tool", shape="parallelogram", attributes={"tool_command": tool_command})


class TestParseVars:
    def test_simple_pair(self):
        assert _parse_vars(["key=value"]) == {"key": "value"}

    def test_multiple_pairs(self):
        result = _parse_vars(["a=1", "b=2", "c=3"])
        assert result == {"a": "1", "b": "2", "c": "3"}

    def test_dotted_key(self):
        result = _parse_vars(["input.pr=42"])
        assert result == {"input.pr": "42"}

    def test_value_with_equals(self):
        result = _parse_vars(["msg=hello=world"])
        assert result == {"msg": "hello=world"}

    def test_value_with_special_characters(self):
        result = _parse_vars(["repo=owner/repo", "msg=hello world"])
        assert result == {"repo": "owner/repo", "msg": "hello world"}

    def test_empty_list(self):
        assert _parse_vars([]) == {}

    def test_no_equals_raises(self):
        with pytest.raises(typer.BadParameter, match="Expected key=value"):
            _parse_vars(["noequals"])

    def test_empty_key_raises(self):
        with pytest.raises(typer.BadParameter, match="Empty key"):
            _parse_vars(["=value"])

    def test_empty_value_raises(self):
        with pytest.raises(typer.BadParameter, match="Empty value"):
            _parse_vars(["key="])


class TestVarsFlowIntoContext:
    def test_vars_populate_context(self):
        parsed = _parse_vars(["pr_number=42", "repo=owner/repo"])
        ctx = Context()
        for k, v in parsed.items():
            ctx.set(k, v)
        assert ctx.get("pr_number") == "42"
        assert ctx.get("repo") == "owner/repo"

    def test_tool_command_renders_template(self):
        handler = ToolHandler()
        ctx = Context()
        ctx.set("pr_number", "123")
        node = _make_node(tool_command="echo {{ pr_number }}")
        outcome = handler.handle(node, ctx, _make_graph())
        assert outcome.context_updates["tool.output"] == "123"

    def test_tool_command_renders_dotted_key(self):
        handler = ToolHandler()
        ctx = Context()
        ctx.set("input.pr", "456")
        node = _make_node(tool_command="echo {{ input.pr }}")
        outcome = handler.handle(node, ctx, _make_graph())
        assert outcome.context_updates["tool.output"] == "456"

    def test_tool_command_without_template_unchanged(self):
        handler = ToolHandler()
        node = _make_node(tool_command="echo hello")
        outcome = handler.handle(node, Context(), _make_graph())
        assert outcome.context_updates["tool.output"] == "hello"
