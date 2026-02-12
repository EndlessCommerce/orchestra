from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.tools import StructuredTool

if TYPE_CHECKING:
    from orchestra.tools.registry import Tool


def to_langchain_tool(orchestra_tool: Tool) -> StructuredTool:
    return StructuredTool.from_function(
        func=orchestra_tool.fn,
        name=orchestra_tool.name,
        description=orchestra_tool.description or f"Tool: {orchestra_tool.name}",
    )
