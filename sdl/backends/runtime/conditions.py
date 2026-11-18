"""Evaluating the condition of a flow step.

Specification section 3.2.1 defines the grammar of a condition. The runtime
parses it into the tree of `sdl.flow.expressions` and evaluates that tree
against the Flow State.

The condition is never evaluated as text. A document cannot make the runtime
run anything it did not already do.
"""

from __future__ import annotations

from typing import Any, Mapping

from sdl.flow.expressions import (
    Binary,
    ConditionSyntaxError,
    Literal,
    Node,
    Not,
    Variable,
    parse_condition,
)
from sdl.backends.runtime.state import resolve_path


def evaluate(condition: str | Node, state: Mapping[str, Any]) -> bool:
    """Evaluate a condition against the Flow State."""
    node = condition if isinstance(condition, Node) else parse_condition(condition)
    return bool(_evaluate(node, state))


def _evaluate(node: Node, state: Mapping[str, Any]) -> Any:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Variable):
        return resolve_path(state, node.path)
    if isinstance(node, Not):
        return not _evaluate(node.operand, state)
    if isinstance(node, Binary):
        return _evaluate_binary(node, state)
    raise TypeError(f"Unknown condition node: {node!r}")


def _evaluate_binary(node: Binary, state: Mapping[str, Any]) -> Any:
    if node.operator == "&&":
        return bool(_evaluate(node.left, state)) and bool(_evaluate(node.right, state))
    if node.operator == "||":
        return bool(_evaluate(node.left, state)) or bool(_evaluate(node.right, state))

    left = _evaluate(node.left, state)
    right = _evaluate(node.right, state)

    if node.operator == "==":
        return left == right
    if node.operator == "!=":
        return left != right
    if node.operator == "<":
        return left < right
    if node.operator == "<=":
        return left <= right
    if node.operator == ">":
        return left > right
    if node.operator == ">=":
        return left >= right
    raise TypeError(f"Unknown operator: {node.operator!r}")


__all__ = ["evaluate", "ConditionSyntaxError"]
