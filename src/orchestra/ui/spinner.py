from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from typing import Iterator

_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


@contextmanager
def spinner(message: str = "Thinking...") -> Iterator[None]:
    """Display an ASCII spinner on stderr while a blocking operation runs.

    No-ops if stderr is not a TTY.
    """
    if not sys.stderr.isatty():
        yield
        return

    stop = threading.Event()

    def _spin() -> None:
        idx = 0
        while not stop.is_set():
            frame = _FRAMES[idx % len(_FRAMES)]
            sys.stderr.write(f"\r{frame} {message}")
            sys.stderr.flush()
            idx += 1
            stop.wait(0.08)
        # Clear the spinner line
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join()
