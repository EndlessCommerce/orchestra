from __future__ import annotations

import re

_BRACKET_PATTERN = re.compile(r"^\[(\w)\]\s+(.*)")
_PAREN_PATTERN = re.compile(r"^(\w)\)\s+(.*)")
_DASH_PATTERN = re.compile(r"^(\w)\s*[-–]\s+(.*)")


def parse_accelerator(label: str) -> tuple[str, str]:
    """Extract accelerator key and clean label from an edge label.

    Supports patterns:
        [K] Label  ->  ("K", "Label")
        K) Label   ->  ("K", "Label")
        K - Label  ->  ("K", "Label")
        Label      ->  ("L", "Label")  (first character fallback)

    Returns:
        (key, clean_label) tuple. Key is always uppercase.
    """
    if not label or not label.strip():
        return ("", "")

    text = label.strip()

    m = _BRACKET_PATTERN.match(text)
    if m:
        return (m.group(1).upper(), m.group(2).strip())

    m = _PAREN_PATTERN.match(text)
    if m:
        return (m.group(1).upper(), m.group(2).strip())

    m = _DASH_PATTERN.match(text)
    if m:
        return (m.group(1).upper(), m.group(2).strip())

    # First character fallback
    return (text[0].upper(), text)
