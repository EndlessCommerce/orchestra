from __future__ import annotations

import copy
from typing import Any


class Context:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def snapshot(self) -> dict[str, Any]:
        return dict(self._data)

    def clone(self) -> Context:
        new_ctx = Context()
        new_ctx._data = copy.deepcopy(self._data)
        return new_ctx
