"""Tests for DOT file Graphviz-compatibility linting."""

from pathlib import Path

import pytest

from orchestra.parser.lint import lint_dot, lint_file

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).parent.parent / "examples"


# ── unit tests ──────────────────────────────────────────────────


def test_clean_file_produces_no_warnings() -> None:
    source = """\
digraph clean {
    graph [goal="test"]
    start [shape=Mdiamond]
    exit  [shape=Msquare]
    work  [label="Work", "agent.mode"="interactive"]
    start -> work -> exit
}
"""
    assert lint_dot(source) == []


def test_unquoted_dotted_key_produces_warning() -> None:
    source = """\
digraph bad {
    start [shape=Mdiamond]
    exit  [shape=Msquare]
    work  [label="Work", agent.mode="interactive"]
    start -> work -> exit
}
"""
    warnings = lint_dot(source)
    assert len(warnings) == 1
    assert warnings[0].line == 4
    assert "agent.mode" in warnings[0].message
    assert "quoted" in warnings[0].message.lower()


def test_multiple_dotted_keys_each_warned() -> None:
    source = """\
digraph bad {
    start [shape=Mdiamond]
    exit  [shape=Msquare]
    a [agent.mode="interactive", human.default_choice="a"]
    start -> a -> exit
}
"""
    warnings = lint_dot(source)
    assert len(warnings) == 2
    keys_warned = {w.message.split('"')[1] for w in warnings}
    assert keys_warned == {"agent.mode", "human.default_choice"}


def test_invalid_dot_returns_parse_error() -> None:
    warnings = lint_dot("not valid dot at all {{{")
    assert len(warnings) == 1
    assert "parse error" in warnings[0].message.lower()


def test_comments_are_ignored() -> None:
    source = """\
digraph ok {
    // agent.mode="interactive" is just a comment
    start [shape=Mdiamond]
    exit  [shape=Msquare]
    start -> exit
}
"""
    assert lint_dot(source) == []


# ── example file validation ─────────────────────────────────────


_EXAMPLE_DOTS = sorted(EXAMPLES.rglob("*.dot"))


@pytest.mark.parametrize(
    "dot_path",
    _EXAMPLE_DOTS,
    ids=[str(p.relative_to(EXAMPLES)) for p in _EXAMPLE_DOTS],
)
def test_example_dot_files_are_graphviz_clean(dot_path: Path) -> None:
    """Every example DOT file must parse and have no Graphviz-compat warnings."""
    warnings = lint_file(dot_path)
    if warnings:
        msg = "\n".join(f"  line {w.line}: {w.message}" for w in warnings)
        pytest.fail(f"{dot_path.name} has lint warnings:\n{msg}")


# ── test fixture validation ─────────────────────────────────────


_FIXTURE_DOTS = sorted(FIXTURES.glob("*.dot"))
# Some fixtures are intentionally invalid.
_INVALID_FIXTURES = {"test-undirected.dot", "test-multiple-graphs.dot", "test-invalid.dot"}


@pytest.mark.parametrize(
    "dot_path",
    [p for p in _FIXTURE_DOTS if p.name not in _INVALID_FIXTURES],
    ids=[p.name for p in _FIXTURE_DOTS if p.name not in _INVALID_FIXTURES],
)
def test_fixture_dot_files_are_graphviz_clean(dot_path: Path) -> None:
    """Valid test fixtures should also pass the Graphviz-compat lint."""
    warnings = lint_file(dot_path)
    if warnings:
        msg = "\n".join(f"  line {w.line}: {w.message}" for w in warnings)
        pytest.fail(f"{dot_path.name} has lint warnings:\n{msg}")
