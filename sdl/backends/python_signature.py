"""Reading the signatures of a Python implementation.

Specification section 5.3 requires the validator to check that an
implementation really implements the interface it claims. The realization of an
implementation is code, not specification, so the only way to check it is to
read the code.

This module reads the signatures of a class of a Python file, with the
standard library parser. It never runs the file.

The reader never guesses a type. A parameter without an annotation, or with an
annotation the compatibility engine cannot understand, is left as ``None`` so
that the caller can fail closed (``SDL-E607``) rather than silently accept a
signature it did not verify. A default value does not widen the type: a
parameter declared ``amount: Decimal = 0`` still accepts a ``Decimal``, not
``Decimal | None``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class PythonMethod:
    """The signature of a method of a Python class."""

    name: str
    parameters: List[tuple[str, str]] = field(default_factory=list)
    returns: Optional[str] = None
    #: Whether the method declares ``**kwargs``. Such a method accepts any
    #: keyword argument, so a parameter the contract names is accepted even
    #: when it is not declared by name.
    accepts_any_keyword: bool = False


@dataclass
class PythonClass:
    """The methods of a Python class."""

    name: str
    methods: Dict[str, PythonMethod] = field(default_factory=dict)


def read_class(path: Path, class_name: str) -> Optional[PythonClass]:
    """The methods of a class of a Python file, or None when it cannot be read."""
    try:
        source = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return _read_class(node)
    return None


def _read_class(node: ast.ClassDef) -> PythonClass:
    result = PythonClass(name=node.name)
    for child in node.body:
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if child.name.startswith("_"):
            continue
        result.methods[child.name] = PythonMethod(
            name=child.name,
            parameters=_read_parameters(child.args),
            returns=_annotation(child.returns),
            accepts_any_keyword=child.args.kwarg is not None,
        )
    return result


def _read_parameters(arguments: ast.arguments) -> List[tuple[str, str]]:
    parameters: List[tuple[str, str]] = []
    positional = list(arguments.posonlyargs) + list(arguments.args)
    for argument in positional:
        # A default value changes what a caller may omit, not the type the
        # parameter accepts. Turning ``T = default`` into ``T | None`` was
        # wrong: a default of ``0`` does not make the parameter accept None,
        # and a default of ``None`` is already written as ``Optional<T>``.
        parameters.append((argument.arg, _annotation(argument.annotation)))
    return parameters


def _annotation(node: Optional[ast.expr]) -> Optional[str]:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - an annotation that cannot be written is unknown
        return None
