from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentTurn:
    turn_number: int
    model: str = ""
    provider: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    agent_state: dict[str, Any] = field(default_factory=dict)
    git_sha: str = ""
    commit_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_number": self.turn_number,
            "model": self.model,
            "provider": self.provider,
            "messages": self.messages,
            "tool_calls": self.tool_calls,
            "files_written": self.files_written,
            "token_usage": self.token_usage,
            "agent_state": self.agent_state,
            "git_sha": self.git_sha,
            "commit_message": self.commit_message,
        }
