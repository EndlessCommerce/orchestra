from __future__ import annotations

from pathlib import Path

from lark import Lark, Tree, UnexpectedInput

from orchestra.models.context import Context
from orchestra.models.outcome import Outcome

_GRAMMAR_PATH = Path(__file__).parent / "grammar.lark"
_parser = Lark(_GRAMMAR_PATH.read_text(), parser="earley")


class ConditionParseError(Exception):
    pass


def parse_condition(expr: str) -> Tree:
    try:
        return _parser.parse(expr)
    except UnexpectedInput as e:
        raise ConditionParseError(f"Invalid condition syntax: {e}") from e


def evaluate_condition(expr: str, outcome: Outcome, context: Context) -> bool:
    if not expr or not expr.strip():
        return True

    tree = parse_condition(expr)
    return _evaluate_tree(tree, outcome, context)


def _evaluate_tree(tree: Tree, outcome: Outcome, context: Context) -> bool:
    for clause in tree.children:
        if not _evaluate_clause(clause, outcome, context):
            return False
    return True


def _evaluate_clause(clause: Tree, outcome: Outcome, context: Context) -> bool:
    key_tree, op_tree, literal_tree = clause.children
    key = _resolve_key(key_tree, outcome, context)
    operator = op_tree.data
    literal = _get_literal_value(literal_tree)

    if operator == "eq":
        return key == literal
    elif operator == "neq":
        return key != literal
    else:
        raise ConditionParseError(f"Unknown operator: {operator}")


def _resolve_key(key_tree: Tree, outcome: Outcome, context: Context) -> str:
    token = str(key_tree.children[0])
    if token == "outcome":
        return outcome.status.value.lower()
    elif token == "preferred_label":
        return outcome.preferred_label.lower()
    elif token.startswith("context."):
        context_key = token[len("context."):]
        value = context.get(context_key, "")
        return str(value) if value is not None else ""
    else:
        raise ConditionParseError(f"Unknown key: {token}")


def _get_literal_value(literal_tree: Tree) -> str:
    token = str(literal_tree.children[0])
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    return token
