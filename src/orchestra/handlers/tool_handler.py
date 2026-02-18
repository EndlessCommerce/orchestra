from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING

import jinja2

from orchestra.models.context import Context
from orchestra.prompts.engine import nest_dotted_keys
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.workspace.workspace_manager import WorkspaceManager


class ToolHandler:
    """Executes shell commands for parallelogram-shaped tool nodes.

    Reads ``tool_command`` from node attributes, runs it via subprocess, and
    stores stdout in the ``tool.output`` context key.

    Note: ``shell=True`` is used for flexibility (pipes, redirects, env vars).
    ``tool_command`` values should be static pipeline-developer-authored strings,
    not derived from LLM-generated context values.
    """

    def __init__(self, workspace_manager: WorkspaceManager | None = None) -> None:
        self._workspace_manager = workspace_manager

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        command = node.attributes.get("tool_command")
        if not command:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason="No tool_command specified",
            )

        # Render Jinja2 template variables in tool_command
        if "{{" in command:
            template = jinja2.Template(command, undefined=jinja2.Undefined)
            command = template.render(**nest_dotted_keys(context.snapshot()))

        timeout = self._parse_timeout(node.attributes.get("timeout", "60s"))
        cwd = self._resolve_cwd(graph)

        start = time.monotonic()
        try:
            result = subprocess.run(
                command,
                shell=True,  # noqa: S602
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - start) * 1000)
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=f"Command timed out after {timeout}s",
                context_updates={"tool.duration_ms": duration_ms},
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = result.stdout.strip()

        name = node.attributes.get("name", node.id)
        existing_outputs = context.get(f"tools.{name}.outputs", [])
        accumulated = existing_outputs + [stdout]

        if result.returncode != 0:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=f"Command exited with code {result.returncode}: {result.stderr.strip()}",
                context_updates={
                    "tool.output": stdout,
                    "tool.exit_code": result.returncode,
                    "tool.duration_ms": duration_ms,
                    f"tools.{name}.output": stdout,
                    f"tools.{name}.exit_code": result.returncode,
                    f"tools.{name}.duration_ms": duration_ms,
                    f"tools.{name}.outputs": accumulated,
                },
            )

        return Outcome(
            status=OutcomeStatus.SUCCESS,
            context_updates={
                "tool.output": stdout,
                "tool.exit_code": 0,
                "tool.duration_ms": duration_ms,
                f"tools.{name}.output": stdout,
                f"tools.{name}.exit_code": 0,
                f"tools.{name}.duration_ms": duration_ms,
                f"tools.{name}.outputs": accumulated,
            },
        )

    def _resolve_cwd(self, graph: PipelineGraph) -> str | None:
        if self._workspace_manager is not None and self._workspace_manager.has_workspace:
            repo_contexts = self._workspace_manager._repo_contexts
            if repo_contexts:
                first_ctx = next(iter(repo_contexts.values()))
                return str(first_ctx.path)
        return None

    @staticmethod
    def _parse_timeout(value: str) -> float:
        """Parse a timeout string like '60s', '5m', or plain number."""
        value = str(value).strip()
        if value.endswith("s"):
            return float(value[:-1])
        if value.endswith("m"):
            return float(value[:-1]) * 60
        return float(value)
