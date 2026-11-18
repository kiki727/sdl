"""Type-expression parser and AST for SDL Core 0.2.

Grammar (SDL Core 0.2 §6.1):

    type_expr      := union
    union          := primary { "|" primary }
    primary        := builtin | qualified_name | generic | "(" type_expr ")"
    generic        := qualified_name "<" type_expr { "," type_expr } ">"
    qualified_name := [ scope "::" ] type_id
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

SNAKE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
PASCAL_ID = re.compile(r"^[A-Z][A-Za-z0-9]*$")
PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

SIMPLE_BUILTINS = {
    "String",
    "Boolean",
    "Int",
    "Float",
    "Decimal",
    "UUID",
    "Date",
    "DateTime",
    "Bytes",
    "Unit",
}
GENERIC_ARITY = {"List": 1, "Map": 2, "Result": 2, "Optional": 1}
BUILTINS = SIMPLE_BUILTINS | set(GENERIC_ARITY)
RESERVED_ENUM_VALUES = {name.lower() for name in BUILTINS}


class TypeSyntaxError(Exception):
    def __init__(self, message: str, position: int = 0):
        super().__init__(message)
        self.message = message
        self.position = position


@dataclass(frozen=True)
class TypeName:
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class TypeGeneric:
    name: str
    args: tuple["TypeExpr", ...]

    def __str__(self) -> str:
        return f"{self.name}<{', '.join(str(arg) for arg in self.args)}>"


@dataclass(frozen=True)
class TypeUnion:
    items: tuple["TypeExpr", ...]

    def __str__(self) -> str:
        return " | ".join(str(item) for item in self.items)


TypeExpr = TypeName | TypeGeneric | TypeUnion


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = self._tokenize(text)
        self.index = 0

    @staticmethod
    def _tokenize(text: str) -> list[tuple[str, str, int]]:
        tokens: list[tuple[str, str, int]] = []
        index = 0
        while index < len(text):
            char = text[index]
            if char.isspace():
                index += 1
                continue
            if text.startswith("::", index):
                tokens.append(("SEP", "::", index))
                index += 2
                continue
            if char in "<>,|()":
                tokens.append((char, char, index))
                index += 1
                continue
            if char.isalpha() or char == "_":
                start = index
                while index < len(text) and (text[index].isalnum() or text[index] == "_"):
                    index += 1
                tokens.append(("NAME", text[start:index], start))
                continue
            raise TypeSyntaxError(f"Unexpected character {char!r}.", index)
        tokens.append(("EOF", "", len(text)))
        return tokens

    def _peek(self) -> tuple[str, str, int]:
        return self.tokens[self.index]

    def _accept(self, kind: str) -> tuple[str, str, int] | None:
        if self._peek()[0] == kind:
            token = self._peek()
            self.index += 1
            return token
        return None

    def _expect(self, kind: str) -> tuple[str, str, int]:
        token = self._accept(kind)
        if token is None:
            actual = self._peek()
            raise TypeSyntaxError(f"Expected {kind!r}, found {actual[1] or 'end of input'!r}.", actual[2])
        return token

    def _expect_name(self) -> tuple[str, int]:
        kind, value, position = self._expect("NAME")
        return value, position

    def parse(self) -> TypeExpr:
        expression = self._parse_union()
        if self._peek()[0] != "EOF":
            token = self._peek()
            raise TypeSyntaxError(f"Unexpected token {token[1]!r}.", token[2])
        return expression

    def _parse_union(self) -> TypeExpr:
        items = [self._parse_primary()]
        while self._accept("|") is not None:
            items.append(self._parse_primary())
        if len(items) == 1:
            return items[0]
        return TypeUnion(tuple(items))

    def _parse_primary(self) -> TypeExpr:
        if self._accept("(") is not None:
            expression = self._parse_union()
            self._expect(")")
            return expression

        name, position = self._expect_name()
        if self._accept("SEP") is not None:
            type_name, type_position = self._expect_name()
            if not (SNAKE_ID.match(name) or name == "project"):
                raise TypeSyntaxError(f"Invalid scope name {name!r}.", position)
            if not PASCAL_ID.match(type_name):
                raise TypeSyntaxError(f"Invalid type name {type_name!r}.", type_position)
            name = f"{name}::{type_name}"
        elif not (PASCAL_ID.match(name) or name in BUILTINS):
            raise TypeSyntaxError(f"Invalid type name {name!r}.", position)

        if self._accept("<") is not None:
            args = [self._parse_union()]
            while self._accept(",") is not None:
                args.append(self._parse_union())
            self._expect(">")
            if len(args) == 0:
                raise TypeSyntaxError("Generic type requires at least one argument.", position)
            return TypeGeneric(name, tuple(args))

        return TypeName(name)


def parse(text: str) -> TypeExpr:
    if not isinstance(text, str) or not text.strip():
        raise TypeSyntaxError("Type expression must be a non-empty string.", 0)
    return _Parser(text).parse()


def split_name(name: str) -> tuple[str | None, str]:
    if "::" in name:
        scope, type_name = name.split("::", 1)
        return scope, type_name
    return None, name


def walk(expression: TypeExpr) -> Iterable[TypeExpr]:
    yield expression
    if isinstance(expression, TypeGeneric):
        for arg in expression.args:
            yield from walk(arg)
    elif isinstance(expression, TypeUnion):
        for item in expression.items:
            yield from walk(item)


def normalize(expression: TypeExpr) -> str:
    if isinstance(expression, TypeUnion):
        members: list[str] = []
        for item in expression.items:
            text = normalize(item)
            if text not in members:
                members.append(text)
        return " | ".join(sorted(members))
    return str(expression)
