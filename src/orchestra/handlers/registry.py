from __future__ import annotations

from orchestra.handlers.base import NodeHandler
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.conditional import ConditionalHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.start import StartHandler


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, NodeHandler] = {}

    def register(self, shape: str, handler: NodeHandler) -> None:
        self._handlers[shape] = handler

    def get(self, shape: str) -> NodeHandler | None:
        return self._handlers.get(shape)


def default_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())
    registry.register("box", SimulationCodergenHandler())
    registry.register("diamond", ConditionalHandler())
    return registry
