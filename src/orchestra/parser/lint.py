"""Linter that checks Orchestra DOT files for Graphviz compatibility.

Graphviz requires that attribute keys containing dots (e.g. ``agent.mode``,
``human.default_choice``) are quoted strings. Orchestra's parser accepts both
quoted and unquoted forms, but only the quoted form renders in Graphviz
previewers.

Usage::

    from orchestra.parser.lint import lint_dot

    warnings = lint_dot(source_text)
    for w in warnings:
        print(f"line {w.line}: {w.message}")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from orchestra.parser.parser import DotParseError, parse_dot


@dataclass
class LintWarning:
    line: int
    column: int
    message: str


# Matches an unquoted qualified id used as an attribute key, e.g.:
#   agent.mode="interactive"
# but NOT inside a string (not preceded by a quote).
_UNQUOTED_QUALIFIED_KEY = re.compile(
    r"""
    (?<!")              # not preceded by a quote
    \b                  # word boundary
    ([A-Za-z_]\w*       # first segment
      (?:\.[A-Za-z_]\w*)+)  # dot-separated segments
    \s*=                # followed by =
    """,
    re.VERBOSE,
)


def lint_dot(source: str) -> list[LintWarning]:
    """Return warnings for Orchestra DOT source that would break Graphviz.

    Currently checks:
    - Unquoted dot-separated attribute keys (e.g. ``agent.mode``).
    - Basic parse validity via Orchestra's own parser.
    """
    warnings: list[LintWarning] = []

    # Check parse validity first.
    try:
        parse_dot(source)
    except DotParseError as exc:
        warnings.append(LintWarning(line=0, column=0, message=f"Parse error: {exc}"))
        return warnings

    # Scan for unquoted qualified keys.
    for lineno, line in enumerate(source.splitlines(), start=1):
        # Skip comments.
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue

        for match in _UNQUOTED_QUALIFIED_KEY.finditer(line):
            key = match.group(1)
            col = match.start(1) + 1
            warnings.append(
                LintWarning(
                    line=lineno,
                    column=col,
                    message=f'Unquoted dotted key "{key}" will fail in Graphviz. Use "{key}" (quoted) instead.',
                )
            )

    return warnings


def lint_file(path: Path) -> list[LintWarning]:
    """Convenience wrapper that reads a file and lints it."""
    return lint_dot(path.read_text())
