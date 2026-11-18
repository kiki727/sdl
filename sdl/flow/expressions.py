"""The expression grammar of a flow condition.

Specification section 3.2.1:

    expr        := logical_or ;
    logical_or  := logical_and { "||" logical_and }
    logical_and := unary { "&&" unary }
    unary       := "!" unary | comparison
    comparison  := operand ( "==" | "!=" | ">" | "<" | ">=" | "<=" ) operand
    operand     := variable | literal
    variable    := path_to_state
    literal     := string_lit | number_lit | bool_lit

The parser produces a tree. A back end renders the tree in its own language,
so that a condition can never be injected into the generated source as raw
text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Union


class ConditionSyntaxError(Exception):
    """A condition that does not follow the grammar."""

    def __init__(self, message: str, position: int = 0):
        super().__init__(message)
        self.message = message
        self.position = position


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Literal:
    """A constant."""

    value: Any


@dataclass(frozen=True)
class Variable:
    """A path into the Flow State."""

    path: str


@dataclass(frozen=True)
class Not:
    """The negation of an expression."""

    operand: "Node"


@dataclass(frozen=True)
class Binary:
    """A comparison or a logical operation."""

    operator: str
    left: "Node"
    right: "Node"


Node = Union[Literal, Variable, Not, Binary]

_COMPARISON_OPERATORS = ("==", "!=", ">=", "<=", ">", "<")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = self._tokenize(text)
        self.index = 0

    @staticmethod
    def _tokenize(text: str) -> list[tuple[str, str, int]]:
        tokens: list[tuple[str, str, int]] = []
        index = 0
        length = len(text)
        while index < length:
            char = text[index]
            if char.isspace():
                index += 1
                continue
            if char in "\"'":
                quote = char
                start = index
                index += 1
                while index < length and text[index] != quote:
                    index += 2 if text[index] == "\\" else 1
                if index >= length:
                    raise ConditionSyntaxError("Unterminated string literal.", start)
                index += 1
                tokens.append(("STRING", text[start:index], start))
                continue
            if char.isdigit():
                start = index
                while index < length and (text[index].isdigit() or text[index] == "."):
                    index += 1
                tokens.append(("NUMBER", text[start:index], start))
                continue
            if char.isalpha() or char == "_":
                start = index
                while index < length:
                    if text[index].isalnum() or text[index] == "_":
                        index += 1
                        continue
                    # A state path continues with a dot: status.is_valid
                    if (
                        text[index] == "."
                        and index + 1 < length
                        and (text[index + 1].isalpha() or text[index + 1] == "_")
                    ):
                        index += 1
                        continue
                    break
                tokens.append(("NAME", text[start:index], start))
                continue
            for operator in ("||", "&&", "==", "!=", ">=", "<="):
                if text.startswith(operator, index):
                    tokens.append(("OP", operator, index))
                    index += len(operator)
                    break
            else:
                if char in "<>":
                    tokens.append(("OP", char, index))
                    index += 1
                    continue
                if char == "!":
                    tokens.append(("NOT", char, index))
                    index += 1
                    continue
                raise ConditionSyntaxError(f"Unexpected character {char!r}.", index)
        tokens.append(("EOF", "", length))
        return tokens

    def _peek(self) -> tuple[str, str, int]:
        return self.tokens[self.index]

    def _accept(self, kind: str, value: str | None = None) -> tuple[str, str, int] | None:
        token = self._peek()
        if token[0] == kind and (value is None or token[1] == value):
            self.index += 1
            return token
        return None

    def parse(self) -> Node:
        node = self._logical_or()
        token = self._peek()
        if token[0] != "EOF":
            raise ConditionSyntaxError(f"Unexpected token {token[1]!r}.", token[2])
        return node

    def _logical_or(self) -> Node:
        node = self._logical_and()
        while self._accept("OP", "||") is not None:
            node = Binary("||", node, self._logical_and())
        return node

    def _logical_and(self) -> Node:
        node = self._unary()
        while self._accept("OP", "&&") is not None:
            node = Binary("&&", node, self._unary())
        return node

    def _unary(self) -> Node:
        if self._accept("NOT") is not None:
            return Not(self._unary())
        return self._comparison()

    def _comparison(self) -> Node:
        left = self._operand()
        for operator in _COMPARISON_OPERATORS:
            if self._accept("OP", operator) is not None:
                return Binary(operator, left, self._operand())
        return left

    def _operand(self) -> Node:
        token = self._peek()
        if token[0] == "STRING":
            self.index += 1
            return Literal(_unquote(token[1]))
        if token[0] == "NUMBER":
            self.index += 1
            text = token[1]
            return Literal(float(text) if "." in text else int(text))
        if token[0] == "NAME":
            self.index += 1
            if token[1] == "true":
                return Literal(True)
            if token[1] == "false":
                return Literal(False)
            return Variable(token[1])
        raise ConditionSyntaxError(
            f"Expected a variable or a literal, found {token[1] or 'end of input'!r}.",
            token[2],
        )


def _unquote(text: str) -> str:
    body = text[1:-1]
    return body.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def parse_condition(text: str) -> Node:
    """Parse a condition into a tree."""
    return _Parser(text).parse()


def variables(node: Node) -> list[str]:
    """The state paths a condition reads, in the order they appear."""
    found: list[str] = []

    def walk(current: Node) -> None:
        if isinstance(current, Variable):
            if current.path not in found:
                found.append(current.path)
        elif isinstance(current, Not):
            walk(current.operand)
        elif isinstance(current, Binary):
            walk(current.left)
            walk(current.right)

    walk(node)
    return found


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_python(node: Node, state: str = "state") -> str:
    """Render a condition as a Python expression.

    The result never contains anything the document wrote, apart from the
    names of the state paths, which are emitted as dictionary lookups. A
    condition therefore cannot inject code into the generated source.
    """
    if isinstance(node, Literal):
        if isinstance(node.value, bool):
            return "True" if node.value else "False"
        if isinstance(node.value, str):
            return repr(node.value)
        return str(node.value)
    if isinstance(node, Variable):
        return _render_path(node.path, state)
    if isinstance(node, Not):
        return f"(not {render_python(node.operand, state)})"
    if isinstance(node, Binary):
        operator = {"&&": "and", "||": "or"}.get(node.operator, node.operator)
        left = render_python(node.left, state)
        right = render_python(node.right, state)
        return f"({left} {operator} {right})"
    raise TypeError(f"Unknown condition node: {node!r}")


def _render_path(path: str, state: str) -> str:
    parts = path.split(".")
    rendered = f'{state}[{parts[0]!r}]'
    for part in parts[1:]:
        rendered += f".{part}"
    return rendered


def render_typescript(node: Node, state: str = "state") -> str:
    """Render a condition as a TypeScript expression.

    The same guarantee as :func:`render_python`: the result carries only the
    names of the state paths, as property accesses on the state object, so a
    condition cannot inject code into the generated source.
    """
    if isinstance(node, Literal):
        if isinstance(node.value, bool):
            return "true" if node.value else "false"
        if isinstance(node.value, str):
            return json.dumps(node.value, ensure_ascii=False)
        return str(node.value)
    if isinstance(node, Variable):
        return _render_typescript_path(node.path, state)
    if isinstance(node, Not):
        return f"!({render_typescript(node.operand, state)})"
    if isinstance(node, Binary):
        left = render_typescript(node.left, state)
        right = render_typescript(node.right, state)
        return f"({left} {node.operator} {right})"
    raise TypeError(f"Unknown condition node: {node!r}")


def _render_typescript_path(path: str, state: str) -> str:
    parts = path.split(".")
    rendered = f"{state}[{json.dumps(parts[0], ensure_ascii=False)}]"
    for part in parts[1:]:
        rendered += f".{part}"
    return rendered
