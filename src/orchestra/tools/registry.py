from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    schema: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str | None = None,
        description: str = "",
        schema: dict[str, Any] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or fn.__name__.replace("_", "-")
            self._tools[tool_name] = Tool(
                name=tool_name,
                description=description or fn.__doc__ or "",
                fn=fn,
                schema=schema or {},
            )
            return fn

        return decorator

    def register_tool(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            available = ", ".join(sorted(self._tools)) or "(none)"
            raise KeyError(f"Unknown tool '{name}'. Available tools: {available}")
        return self._tools[name]

    def get_tools(self, names: list[str]) -> list[Tool]:
        return [self.get(name) for name in names]

    def list_tools(self) -> list[str]:
        return sorted(self._tools)
