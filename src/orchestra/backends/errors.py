from __future__ import annotations

import re


def sanitize_error(error: str) -> str:
    """Strip API keys and bearer tokens from error messages."""
    error = re.sub(r"(sk-|key-)[a-zA-Z0-9_-]+", "[REDACTED]", error)
    error = re.sub(r"Bearer\s+[a-zA-Z0-9_-]+", "Bearer [REDACTED]", error)
    return error
