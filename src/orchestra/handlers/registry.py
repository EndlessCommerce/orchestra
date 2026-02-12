from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.handlers.base import NodeHandler
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.codergen_handler import CodergenHandler
from orchestra.handlers.conditional import ConditionalHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.start import StartHandler
from orchestra.handlers.wait_human import WaitHumanHandler

if TYPE_CHECKING:
    from orchestra.backends.protocol import CodergenBackend
    from orchestra.config.settings import OrchestraConfig
    from orchestra.interviewer.base import Interviewer


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
    interviewer: Interviewer | None = None,
) -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())

    if backend is not None:
        standard_handler = CodergenHandler(backend=backend, config=config)

        if interviewer is not None:
            from orchestra.backends.protocol import ConversationalBackend
            from orchestra.handlers.codergen_dispatcher import CodergenDispatcher
            from orchestra.handlers.interactive import InteractiveHandler

            if isinstance(backend, ConversationalBackend):
                interactive_handler = InteractiveHandler(
                    backend=backend, interviewer=interviewer, config=config
                )
                box_handler = CodergenDispatcher(
                    standard=standard_handler, interactive=interactive_handler
                )
            else:
                box_handler = standard_handler
        else:
            box_handler = standard_handler
    else:
        box_handler = SimulationCodergenHandler()

    registry.register("box", box_handler)
    registry.register("diamond", ConditionalHandler())

    # Human gate handler
    if interviewer is not None:
        registry.register("hexagon", WaitHumanHandler(interviewer))
    else:
        from orchestra.interviewer.auto_approve import AutoApproveInterviewer

        registry.register("hexagon", WaitHumanHandler(AutoApproveInterviewer()))

    return registry
