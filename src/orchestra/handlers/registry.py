from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.handlers.base import NodeHandler
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.codergen_handler import CodergenHandler
from orchestra.handlers.conditional import ConditionalHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.start import StartHandler

if TYPE_CHECKING:
    from orchestra.backends.protocol import CodergenBackend
    from orchestra.config.settings import OrchestraConfig


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, NodeHandler] = {}

    def register(self, shape: str, handler: NodeHandler) -> None:
        self._handlers[shape] = handler

    def get(self, shape: str) -> NodeHandler | None:
        return self._handlers.get(shape)


def default_registry(
    backend: CodergenBackend | None = None,
    config: OrchestraConfig | None = None,
) -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())

    if backend is not None:
        handler = CodergenHandler(backend=backend, config=config)
    else:
        handler = SimulationCodergenHandler()

    registry.register("box", handler)
    registry.register("diamond", ConditionalHandler())
    return registry
