from pathlib import Path

import pytest

from orchestra.backends.write_tracker import WriteTracker
from orchestra.config.settings import WorkspaceToolConfig
from orchestra.workspace.repo_context import RepoContext
from orchestra.workspace.repo_tools import create_repo_tools, create_workspace_tools


@pytest.fixture()
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "my-repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hello')\n")
    return repo


@pytest.fixture()
def repo_ctx(repo_dir: Path) -> RepoContext:
    return RepoContext(name="project", path=repo_dir, branch="main", base_sha="a" * 40)


@pytest.fixture()
def tracker() -> WriteTracker:
    return WriteTracker()


class TestToolNaming:
    def test_single_repo_tool_names(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        names = {t.name for t in tools}
        assert names == {
            "project__read-file",
            "project__write-file",
            "project__edit-file",
            "project__search-code",
        }

    def test_multi_repo_tool_names(self, repo_dir: Path, tracker: WriteTracker) -> None:
        repos = {
            "backend": RepoContext(name="backend", path=repo_dir, branch="main", base_sha="a" * 40),
            "frontend": RepoContext(name="frontend", path=repo_dir, branch="main", base_sha="b" * 40),
        }
        tools = create_repo_tools(repos, tracker)
        names = {t.name for t in tools}
        assert "backend__read-file" in names
        assert "frontend__read-file" in names
        assert len(tools) == 8  # 4 tools per repo


class TestReadFile:
    def test_reads_file(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        read_tool = next(t for t in tools if t.name == "project__read-file")
        result = read_tool.fn(path="src/main.py")
        assert "hello" in result

    def test_file_not_found(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        read_tool = next(t for t in tools if t.name == "project__read-file")
        result = read_tool.fn(path="nonexistent.py")
        assert "Error" in result


class TestWriteFile:
    def test_writes_file(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        write_tool = next(t for t in tools if t.name == "project__write-file")
        result = write_tool.fn(path="new.txt", content="hello world")
        assert "Wrote" in result
        assert (repo_ctx.path / "new.txt").read_text() == "hello world"

    def test_records_write(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        write_tool = next(t for t in tools if t.name == "project__write-file")
        write_tool.fn(path="tracked.txt", content="data")
        flushed = tracker.flush()
        assert len(flushed) == 1
        assert "tracked.txt" in flushed[0]


class TestEditFile:
    def test_edits_file(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        edit_tool = next(t for t in tools if t.name == "project__edit-file")
        result = edit_tool.fn(path="src/main.py", old_text="hello", new_text="world")
        assert "Edited" in result
        content = (repo_ctx.path / "src" / "main.py").read_text()
        assert "world" in content

    def test_records_edit(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        edit_tool = next(t for t in tools if t.name == "project__edit-file")
        edit_tool.fn(path="src/main.py", old_text="hello", new_text="world")
        flushed = tracker.flush()
        assert len(flushed) == 1

    def test_text_not_found(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        edit_tool = next(t for t in tools if t.name == "project__edit-file")
        result = edit_tool.fn(path="src/main.py", old_text="nonexistent", new_text="x")
        assert "Error" in result


class TestPathTraversal:
    def test_rejects_path_escape(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        read_tool = next(t for t in tools if t.name == "project__read-file")
        result = read_tool.fn(path="../../etc/passwd")
        assert "Error" in result

    def test_rejects_write_escape(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        write_tool = next(t for t in tools if t.name == "project__write-file")
        result = write_tool.fn(path="../outside.txt", content="bad")
        assert "Error" in result

    def test_rejects_edit_escape(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        edit_tool = next(t for t in tools if t.name == "project__edit-file")
        result = edit_tool.fn(path="../../escape.py", old_text="x", new_text="y")
        assert "Error" in result


class TestSearchCode:
    def test_searches_repo(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        search_tool = next(t for t in tools if t.name == "project__search-code")
        result = search_tool.fn(pattern="hello")
        assert "hello" in result

    def test_no_matches(self, repo_ctx: RepoContext, tracker: WriteTracker) -> None:
        tools = create_repo_tools({"project": repo_ctx}, tracker)
        search_tool = next(t for t in tools if t.name == "project__search-code")
        result = search_tool.fn(pattern="zzz_no_match_zzz")
        assert "No matches" in result


class TestWorkspaceTools:
    def test_creates_repo_scoped_tool(self, repo_ctx: RepoContext) -> None:
        tool_configs = {
            "project": {
                "run-tests": WorkspaceToolConfig(command="echo ok"),
            },
        }
        tools = create_workspace_tools(tool_configs, {"project": repo_ctx})
        assert len(tools) == 1
        assert tools[0].name == "project__run-tests"

    def test_tool_runs_command_in_repo_dir(self, repo_ctx: RepoContext) -> None:
        tool_configs = {
            "project": {
                "list-files": WorkspaceToolConfig(command="ls src/main.py"),
            },
        }
        tools = create_workspace_tools(tool_configs, {"project": repo_ctx})
        result = tools[0].fn()
        assert "main.py" in result

    def test_uses_custom_description(self, repo_ctx: RepoContext) -> None:
        tool_configs = {
            "project": {
                "run-tests": WorkspaceToolConfig(command="pytest", description="Run the test suite"),
            },
        }
        tools = create_workspace_tools(tool_configs, {"project": repo_ctx})
        assert tools[0].description == "Run the test suite"

    def test_default_description_includes_command(self, repo_ctx: RepoContext) -> None:
        tool_configs = {
            "project": {
                "run-tests": WorkspaceToolConfig(command="pytest -v"),
            },
        }
        tools = create_workspace_tools(tool_configs, {"project": repo_ctx})
        assert "pytest -v" in tools[0].description

    def test_skips_unknown_repo(self, repo_ctx: RepoContext) -> None:
        tool_configs = {
            "unknown-repo": {
                "run-tests": WorkspaceToolConfig(command="pytest"),
            },
        }
        tools = create_workspace_tools(tool_configs, {"project": repo_ctx})
        assert len(tools) == 0

    def test_multi_repo_tools(self, repo_dir: Path) -> None:
        repos = {
            "backend": RepoContext(name="backend", path=repo_dir, branch="main", base_sha="a" * 40),
            "frontend": RepoContext(name="frontend", path=repo_dir, branch="main", base_sha="b" * 40),
        }
        tool_configs = {
            "backend": {"run-tests": WorkspaceToolConfig(command="rspec")},
            "frontend": {"run-tests": WorkspaceToolConfig(command="npm test")},
        }
        tools = create_workspace_tools(tool_configs, repos)
        names = {t.name for t in tools}
        assert names == {"backend__run-tests", "frontend__run-tests"}

    def test_nonzero_exit_includes_stderr(self, repo_ctx: RepoContext) -> None:
        tool_configs = {
            "project": {
                "fail": WorkspaceToolConfig(command="echo error >&2 && exit 1"),
            },
        }
        tools = create_workspace_tools(tool_configs, {"project": repo_ctx})
        result = tools[0].fn()
        assert "STDERR" in result
        assert "Exit code: 1" in result
