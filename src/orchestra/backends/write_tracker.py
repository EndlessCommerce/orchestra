from __future__ import annotations

import functools
from typing import Any, Callable


class WriteTracker:
    def __init__(self) -> None:
        self._paths: dict[str, None] = {}

    def record(self, path: str) -> None:
        self._paths[path] = None

    def flush(self) -> list[str]:
        paths = list(self._paths)
        self._paths.clear()
        return paths


def modifies_files(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(*args: Any, write_tracker: WriteTracker | None = None, **kwargs: Any) -> Any:
        result = fn(*args, **kwargs)
        if write_tracker is not None and isinstance(result, (str, list)):
            paths = [result] if isinstance(result, str) else result
            for p in paths:
                if isinstance(p, str):
                    write_tracker.record(p)
        return result

    return wrapper
