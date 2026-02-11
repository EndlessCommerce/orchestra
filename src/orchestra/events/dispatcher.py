from __future__ import annotations

from typing import Any

from orchestra.events.observer import EventObserver
from orchestra.events.types import EVENT_TYPE_MAP, Event


class EventDispatcher:
    def __init__(self) -> None:
        self._observers: list[EventObserver] = []

    def add_observer(self, observer: EventObserver) -> None:
        self._observers.append(observer)

    def emit(self, event_type: str, **data: Any) -> None:
        event_cls = EVENT_TYPE_MAP.get(event_type)
        if event_cls is None:
            return
        event = event_cls(**data)
        for observer in self._observers:
            observer.on_event(event)
