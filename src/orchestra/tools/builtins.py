from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from orchestra.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from orchestra.backends.write_tracker import WriteTracker

builtin_registry = ToolRegistry()


@builtin_registry.register(name="read-file", description="Read a file's contents")
def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"Error: file not found: {path}"
    return p.read_text()


@builtin_registry.register(name="write-file", description="Write content to a file")
def write_file(path: str, content: str, write_tracker: WriteTracker | None = None) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    if write_tracker is not None:
        write_tracker.record(path)
    return f"Wrote {len(content)} bytes to {path}"


@builtin_registry.register(name="edit-file", description="Replace text in a file")
def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    write_tracker: WriteTracker | None = None,
) -> str:
    p = Path(path)
    if not p.exists():
        return f"Error: file not found: {path}"
    content = p.read_text()
    if old_text not in content:
        return f"Error: text not found in {path}"
    content = content.replace(old_text, new_text, 1)
    p.write_text(content)
    if write_tracker is not None:
        write_tracker.record(path)
    return f"Edited {path}"


@builtin_registry.register(name="search-code", description="Search for a pattern in files")
def search_code(pattern: str, path: str = ".") -> str:
    try:
        result = subprocess.run(
            ["grep", "-rn", pattern, path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout or "No matches found."
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"Error: {e}"


@builtin_registry.register(name="shell", description="Run a shell command")
def shell(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\nSTDERR: {result.stderr}" if result.stderr else ""
            output += f"\nExit code: {result.returncode}"
        return output
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 60s"
