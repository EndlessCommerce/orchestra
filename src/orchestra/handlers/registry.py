from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.handlers.base import NodeHandler
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.codergen_handler import CodergenHandler
from orchestra.handlers.conditional import ConditionalHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.fan_in_handler import FanInHandler
from orchestra.handlers.parallel_handler import ParallelHandler
from orchestra.handlers.start import StartHandler
from orchestra.handlers.wait_human import WaitHumanHandler

if TYPE_CHECKING:
    from orchestra.backends.protocol import CodergenBackend, OnTurnCallback
    from orchestra.config.settings import OrchestraConfig
    from orchestra.engine.runner import EventEmitter
    from orchestra.interviewer.base import Interviewer
    from orchestra.workspace.workspace_manager import WorkspaceManager


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
    event_emitter: EventEmitter | None = None,
    on_turn: OnTurnCallback | None = None,
    workspace_manager: WorkspaceManager | None = None,
) -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())

    if backend is not None:
        standard_handler = CodergenHandler(backend=backend, config=config, on_turn=on_turn)

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
    registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=event_emitter, workspace_manager=workspace_manager))
    registry.register("tripleoctagon", FanInHandler(backend=backend, workspace_manager=workspace_manager))

    # Human gate handler
    if interviewer is not None:
        registry.register("hexagon", WaitHumanHandler(interviewer))
    else:
        from orchestra.interviewer.auto_approve import AutoApproveInterviewer

        registry.register("hexagon", WaitHumanHandler(AutoApproveInterviewer()))

    return registry
