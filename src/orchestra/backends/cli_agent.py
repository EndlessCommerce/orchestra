from __future__ import annotations

import json
import subprocess
import tempfile
from typing import TYPE_CHECKING

from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.backends.protocol import OnTurnCallback
    from orchestra.models.context import Context
    from orchestra.models.graph import Node


class CLIAgentBackend:
    def __init__(
        self,
        command: str = "claude",
        args: list[str] | None = None,
        timeout: int = 300,
    ) -> None:
        self._command = command
        self._args = args or []
        self._timeout = timeout
        self._conversation_history: list[str] = []

    def run(
        self,
        node: Node,
        prompt: str,
        context: Context,
        on_turn: OnTurnCallback | None = None,
    ) -> str | Outcome:
        context_data = context.snapshot()

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                prefix="orchestra_ctx_",
                delete=False,
            ) as ctx_file:
                json.dump(context_data, ctx_file, default=str)
                ctx_path = ctx_file.name

            env = {"ORCHESTRA_CONTEXT_FILE": ctx_path}

            cmd = [self._command] + self._args
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env={**__import__("os").environ, **env},
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"Exit code: {result.returncode}"
                return Outcome(
                    status=OutcomeStatus.FAIL,
                    failure_reason=error_msg,
                )

            return result.stdout

        except subprocess.TimeoutExpired:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=f"CLI agent timed out after {self._timeout}s",
            )
        except FileNotFoundError:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=f"CLI agent command not found: {self._command}",
            )
        except Exception as e:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=str(e),
            )

    def send_message(
        self,
        node: Node,
        message: str,
        context: Context,
        on_turn: OnTurnCallback | None = None,
    ) -> str | Outcome:
        self._conversation_history.append(f"Human: {message}")
        full_prompt = "\n".join(self._conversation_history)
        result = self.run(node, full_prompt, context, on_turn)
        if isinstance(result, str):
            self._conversation_history.append(f"Assistant: {result}")
        return result

    def reset_conversation(self) -> None:
        self._conversation_history = []
