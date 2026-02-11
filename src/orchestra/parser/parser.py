from __future__ import annotations

import re
from pathlib import Path

from lark import Lark
from lark.exceptions import UnexpectedInput

from orchestra.models.graph import PipelineGraph
from orchestra.parser.transformer import DotTransformer

_GRAMMAR_PATH = Path(__file__).parent / "grammar.lark"

_parser: Lark | None = None


def _get_parser() -> Lark:
    global _parser
    if _parser is None:
        grammar_text = _GRAMMAR_PATH.read_text()
        _parser = Lark(grammar_text, parser="earley", propagate_positions=True)
    return _parser


class DotParseError(Exception):
    pass


def parse_dot(source: str) -> PipelineGraph:
    _validate_source(source)
    parser = _get_parser()
    try:
        tree = parser.parse(source)
    except UnexpectedInput as e:
        raise DotParseError(f"Parse error at line {e.line}, column {e.column}: {e}") from e

    transformer = DotTransformer()
    graph = transformer.transform(tree)
    return graph


def _validate_source(source: str) -> None:
    digraph_count = len(re.findall(r'\bdigraph\b', source))
    if digraph_count > 1:
        raise DotParseError("Multiple digraph blocks are not supported. Only one digraph per file is allowed.")

    undirected = re.search(r'(?<!\w)graph\s*\{', source)
    if undirected:
        has_digraph = re.search(r'\bdigraph\b', source)
        if not has_digraph:
            raise DotParseError("Undirected graphs are not supported. Use 'digraph' for directed graphs.")

    if re.search(r'\b\w+\s*--\s*\w+', source):
        raise DotParseError("Undirected edges (--) are not supported. Use directed edges (->).")
