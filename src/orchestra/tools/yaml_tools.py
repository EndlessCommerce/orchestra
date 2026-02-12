from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from orchestra.tools.registry import Tool, ToolRegistry

if TYPE_CHECKING:
    from orchestra.config.settings import ToolConfig


def load_yaml_tools(tool_configs: list[ToolConfig], registry: ToolRegistry) -> None:
    for config in tool_configs:
        tool = _make_shell_tool(config.name, config.command, config.description)
        registry.register_tool(tool)


def _make_shell_tool(name: str, command: str, description: str) -> Tool:
    def run_command(**kwargs: str) -> str:
        cmd = command
        for key, value in kwargs.items():
            cmd = cmd.replace(f"{{{key}}}", value)
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout
            if result.returncode != 0:
                output += f"\nSTDERR: {result.stderr}" if result.stderr else ""
                output += f"\nExit code: {result.returncode}"
            return output
        except subprocess.TimeoutExpired:
            return f"Error: command '{name}' timed out after 120s"

    return Tool(
        name=name,
        description=description or f"Run: {command}",
        fn=run_command,
    )
