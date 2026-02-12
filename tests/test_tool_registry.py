import pytest

from orchestra.config.settings import ToolConfig
from orchestra.tools.builtins import builtin_registry
from orchestra.tools.registry import Tool, ToolRegistry
from orchestra.tools.yaml_tools import load_yaml_tools


class TestToolRegistryBasics:
    def test_register_via_decorator(self):
        registry = ToolRegistry()

        @registry.register(name="my-tool", description="A test tool")
        def my_tool(x: str) -> str:
            return x

        tool = registry.get("my-tool")
        assert tool.name == "my-tool"
        assert tool.description == "A test tool"
        assert tool.fn("hello") == "hello"

    def test_register_auto_name(self):
        registry = ToolRegistry()

        @registry.register()
        def my_custom_tool() -> str:
            return "result"

        tool = registry.get("my-custom-tool")
        assert tool.name == "my-custom-tool"

    def test_register_tool_directly(self):
        registry = ToolRegistry()
        tool = Tool(name="direct", description="Direct", fn=lambda: "ok")
        registry.register_tool(tool)
        assert registry.get("direct").fn() == "ok"

    def test_unknown_tool_raises(self):
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="Unknown tool 'missing'"):
            registry.get("missing")

    def test_unknown_tool_lists_available(self):
        registry = ToolRegistry()

        @registry.register(name="alpha")
        def alpha() -> str:
            return ""

        with pytest.raises(KeyError, match="alpha"):
            registry.get("beta")

    def test_list_tools(self):
        registry = ToolRegistry()

        @registry.register(name="b-tool")
        def b() -> str:
            return ""

        @registry.register(name="a-tool")
        def a() -> str:
            return ""

        assert registry.list_tools() == ["a-tool", "b-tool"]


class TestGetTools:
    def test_get_tools_by_names(self):
        registry = ToolRegistry()

        @registry.register(name="read-file")
        def read() -> str:
            return "read"

        @registry.register(name="write-file")
        def write() -> str:
            return "write"

        @registry.register(name="shell")
        def sh() -> str:
            return "shell"

        tools = registry.get_tools(["read-file", "shell"])
        assert len(tools) == 2
        assert tools[0].name == "read-file"
        assert tools[1].name == "shell"

    def test_get_tools_restriction(self):
        registry = ToolRegistry()

        @registry.register(name="read-file")
        def read() -> str:
            return "read"

        @registry.register(name="write-file")
        def write() -> str:
            return "write"

        tools = registry.get_tools(["read-file"])
        assert len(tools) == 1
        assert tools[0].name == "read-file"

    def test_get_tools_unknown_raises(self):
        registry = ToolRegistry()

        @registry.register(name="read-file")
        def read() -> str:
            return "read"

        with pytest.raises(KeyError, match="nonexistent"):
            registry.get_tools(["read-file", "nonexistent"])


class TestBuiltinTools:
    def test_builtin_read_file_registered(self):
        tool = builtin_registry.get("read-file")
        assert tool.name == "read-file"

    def test_builtin_write_file_registered(self):
        tool = builtin_registry.get("write-file")
        assert tool.name == "write-file"

    def test_builtin_edit_file_registered(self):
        tool = builtin_registry.get("edit-file")
        assert tool.name == "edit-file"

    def test_builtin_search_code_registered(self):
        tool = builtin_registry.get("search-code")
        assert tool.name == "search-code"

    def test_builtin_shell_registered(self):
        tool = builtin_registry.get("shell")
        assert tool.name == "shell"

    def test_read_file_returns_content(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        tool = builtin_registry.get("read-file")
        assert tool.fn(str(f)) == "hello world"

    def test_read_file_not_found(self):
        tool = builtin_registry.get("read-file")
        result = tool.fn("/nonexistent/file.txt")
        assert "Error" in result

    def test_write_file_creates_file(self, tmp_path):
        from orchestra.backends.write_tracker import WriteTracker

        tracker = WriteTracker()
        path = str(tmp_path / "out.txt")
        tool = builtin_registry.get("write-file")
        tool.fn(path, "content", write_tracker=tracker)
        assert (tmp_path / "out.txt").read_text() == "content"
        assert tracker.flush() == [path]

    def test_edit_file_replaces_text(self, tmp_path):
        from orchestra.backends.write_tracker import WriteTracker

        tracker = WriteTracker()
        f = tmp_path / "test.py"
        f.write_text("foo = 1\nbar = 2\n")
        tool = builtin_registry.get("edit-file")
        tool.fn(str(f), "foo = 1", "foo = 42", write_tracker=tracker)
        assert f.read_text() == "foo = 42\nbar = 2\n"
        assert tracker.flush() == [str(f)]


class TestYamlTools:
    def test_load_yaml_shell_tool(self):
        registry = ToolRegistry()
        configs = [ToolConfig(name="run-tests", command="echo test", description="Run tests")]
        load_yaml_tools(configs, registry)
        tool = registry.get("run-tests")
        assert tool.name == "run-tests"
        assert tool.description == "Run tests"

    def test_yaml_tool_callable(self):
        registry = ToolRegistry()
        configs = [ToolConfig(name="echo-tool", command="echo hello")]
        load_yaml_tools(configs, registry)
        tool = registry.get("echo-tool")
        result = tool.fn()
        assert "hello" in result

    def test_multiple_yaml_tools(self):
        registry = ToolRegistry()
        configs = [
            ToolConfig(name="tool-a", command="echo a"),
            ToolConfig(name="tool-b", command="echo b"),
        ]
        load_yaml_tools(configs, registry)
        assert registry.get("tool-a").name == "tool-a"
        assert registry.get("tool-b").name == "tool-b"
