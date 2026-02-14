from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from orchestra.tools.registry import Tool
from orchestra.workspace.repo_context import RepoContext

if TYPE_CHECKING:
    from orchestra.backends.write_tracker import WriteTracker
    from orchestra.config.settings import WorkspaceToolConfig


def _resolve_path(repo_path: Path, relative_path: str) -> Path:
    resolved = (repo_path / relative_path).resolve()
    repo_resolved = repo_path.resolve()
    if not str(resolved).startswith(str(repo_resolved)):
        raise ValueError(f"Path escapes repo directory: {relative_path}")
    return resolved


def create_repo_tools(
    repos: dict[str, RepoContext],
    write_tracker: WriteTracker,
) -> list[Tool]:
    tools: list[Tool] = []
    for repo_name, repo_ctx in repos.items():
        tools.extend(_tools_for_repo(repo_name, repo_ctx, write_tracker))
    return tools


def _tools_for_repo(
    repo_name: str,
    repo_ctx: RepoContext,
    write_tracker: WriteTracker,
) -> list[Tool]:
    repo_path = repo_ctx.path

    def read_file(path: str) -> str:
        try:
            p = _resolve_path(repo_path, path)
        except ValueError as e:
            return f"Error: {e}"
        if not p.exists():
            return f"Error: file not found: {path}"
        return p.read_text()

    def write_file(path: str, content: str) -> str:
        try:
            p = _resolve_path(repo_path, path)
        except ValueError as e:
            return f"Error: {e}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        write_tracker.record(str(p))
        return f"Wrote {len(content)} bytes to {path}"

    def edit_file(path: str, old_text: str, new_text: str) -> str:
        try:
            p = _resolve_path(repo_path, path)
        except ValueError as e:
            return f"Error: {e}"
        if not p.exists():
            return f"Error: file not found: {path}"
        file_content = p.read_text()
        if old_text not in file_content:
            return f"Error: text not found in {path}"
        file_content = file_content.replace(old_text, new_text, 1)
        p.write_text(file_content)
        write_tracker.record(str(p))
        return f"Edited {path}"

    def search_code(pattern: str, path: str = ".") -> str:
        try:
            search_path = _resolve_path(repo_path, path)
        except ValueError as e:
            return f"Error: {e}"
        try:
            result = subprocess.run(
                ["grep", "-rn", pattern, str(search_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout or "No matches found."
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return f"Error: {e}"

    return [
        Tool(
            name=f"{repo_name}__read-file",
            description=f"Read a file in the {repo_name} repo",
            fn=read_file,
            schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative file path"}},
                "required": ["path"],
            },
        ),
        Tool(
            name=f"{repo_name}__write-file",
            description=f"Write content to a file in the {repo_name} repo",
            fn=write_file,
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name=f"{repo_name}__edit-file",
            description=f"Replace text in a file in the {repo_name} repo",
            fn=edit_file,
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "old_text": {"type": "string", "description": "Text to find"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        ),
        Tool(
            name=f"{repo_name}__search-code",
            description=f"Search for a pattern in the {repo_name} repo",
            fn=search_code,
            schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern"},
                    "path": {"type": "string", "description": "Relative path to search in", "default": "."},
                },
                "required": ["pattern"],
            },
        ),
    ]


def create_workspace_tools(
    workspace_tools: dict[str, dict[str, WorkspaceToolConfig]],
    repos: dict[str, RepoContext],
) -> list[Tool]:
    """Create repo-scoped custom tools from workspace.tools config."""
    tools: list[Tool] = []
    for repo_name, tool_defs in workspace_tools.items():
        repo_ctx = repos.get(repo_name)
        if repo_ctx is None:
            continue
        for tool_name, tool_config in tool_defs.items():
            tools.append(_make_workspace_tool(
                repo_name, tool_name, tool_config, repo_ctx.path,
            ))
    return tools


def _make_workspace_tool(
    repo_name: str,
    tool_name: str,
    tool_config: WorkspaceToolConfig,
    repo_path: Path,
) -> Tool:
    command = tool_config.command

    def run_command() -> str:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(repo_path),
            )
            output = result.stdout
            if result.returncode != 0:
                output += f"\nSTDERR: {result.stderr}" if result.stderr else ""
                output += f"\nExit code: {result.returncode}"
            return output or "No output."
        except subprocess.TimeoutExpired:
            return f"Error: '{repo_name}__{tool_name}' timed out after 120s"

    return Tool(
        name=f"{repo_name}__{tool_name}",
        description=tool_config.description or f"Run `{command}` in the {repo_name} repo",
        fn=run_command,
        schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
