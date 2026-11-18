"""Assignability, as Core 0.2 section 6.7 defines it.

After alias expansion:

* ``T`` is assignable to ``T``.
* ``T`` is assignable to ``Optional<T>``.
* ``Optional<T>`` is assignable to ``Optional<U>`` if ``T`` is assignable to ``U``.
* ``T`` is assignable to ``T | U``.
* ``T | U`` is assignable to ``V`` if both ``T`` and ``U`` are assignable to ``V``.
* ``List<T>`` is invariant: ``List<A>`` is not assignable to ``List<B>`` unless
  ``A`` is identical to ``B``.
* ``Map<K,V>`` is invariant.
* ``Result<T,E>`` is covariant in ``T`` and ``E``.
* Classes and enums are nominal; the type identity is the name, not the
  structure.
* ``Unit`` is not assignable to any other type.
* ``null`` is assignable only to ``Optional<T>``.
* There are no implicit conversions.
"""

from __future__ import annotations

from typing import Optional

from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import SymbolId, TypeKind, TypeRef, TypeSymbol
from sdl.types import expressions as sdl_types

#: The generic types that are invariant in their arguments.
INVARIANT = ("List", "Map")

#: The generic types that are covariant in their arguments.
COVARIANT = ("Result",)

#: The name of the unit type.
UNIT = "Unit"

#: The name of the optional type.
OPTIONAL = "Optional"


class TypeEnvironment:
    """Answers whether a type is assignable to another."""

    def __init__(self, graph: SymbolGraph):
        self.graph = graph

    # -- the public rule -----------------------------------------------------

    def assignable(self, source: Optional[TypeRef], target: Optional[TypeRef]) -> bool:
        """Whether a value of the source type may be used as the target type."""
        if source is None or target is None:
            return False
        source = self.expand(source)
        target = self.expand(target)
        return self._assignable(source, target, set())

    def is_optional(self, reference: TypeRef) -> bool:
        """Whether a reference is an ``Optional<T>``.

        The base of a generic is the *identifier* of the type, which is not
        its name: the identifier of a built-in is a digest, so the name has to
        be resolved through the graph.
        """
        if reference.kind != "generic":
            return False
        return self._name_of(reference.base) == OPTIONAL

    # -- alias expansion -----------------------------------------------------

    def expand(self, reference: TypeRef) -> TypeRef:
        """Expand the aliases of a type."""
        seen: set[str] = set()
        while True:
            base = reference.base
            if base is None:
                return reference
            symbol = self.graph.get_symbol(base)
            if not isinstance(symbol, TypeSymbol) or symbol.type_kind != TypeKind.ALIAS:
                return reference
            key = str(base)
            if key in seen:
                return reference
            seen.add(key)
            alias = symbol.metadata.get("alias_type_ref")
            if alias is None:
                return reference
            reference = alias

    # -- the rules -----------------------------------------------------------

    def _assignable(self, source: TypeRef, target: TypeRef, seen: set[tuple[str, str]]) -> bool:
        # T is assignable to T.
        if source.kind == "named" and target.kind == "named":
            return source.base == target.base

        # Unit is not assignable to any other type.
        if self._is_unit(source):
            return self._is_unit(target)

        # T is assignable to T | U.
        if target.kind == "union":
            return any(self._assignable(source, member, seen) for member in target.arguments)

        # T | U is assignable to V if both T and U are assignable to V.
        if source.kind == "union":
            return all(self._assignable(member, target, seen) for member in source.arguments)

        if source.kind == "named" and self.is_optional(target):
            # T is assignable to Optional<T>.
            return self._assignable(source, target.arguments[0], seen) if target.arguments else True

        if self.is_optional(source) and self.is_optional(target):
            # Optional<T> is assignable to Optional<U> if T is assignable to U.
            if not source.arguments or not target.arguments:
                return False
            return self._assignable(source.arguments[0], target.arguments[0], seen)

        if source.kind == "generic" and target.kind == "generic":
            source_name = self._name_of(source.base)
            target_name = self._name_of(target.base)
            if source_name != target_name:
                return False

            key = (str(source.base), str(target.base))
            if key in seen:
                return False
            seen = seen | {key}

            if source_name in INVARIANT:
                # List<T> and Map<K,V> are invariant.
                return all(
                    self._identical(a, b) for a, b in zip(source.arguments, target.arguments)
                ) and len(source.arguments) == len(target.arguments)

            if source_name in COVARIANT:
                # Result<T,E> is covariant in T and E.
                return all(
                    self._assignable(a, b, seen)
                    for a, b in zip(source.arguments, target.arguments)
                ) and len(source.arguments) == len(target.arguments)

            return all(
                self._identical(a, b) for a, b in zip(source.arguments, target.arguments)
            ) and len(source.arguments) == len(target.arguments)

        return False

    # -- helpers -------------------------------------------------------------

    def _identical(self, left: SymbolId, right: SymbolId) -> bool:
        return left == right

    def _name_of(self, type_id: Optional[SymbolId]) -> str:
        if type_id is None:
            return ""
        symbol = self.graph.get_symbol(type_id)
        return symbol.name if symbol is not None else str(type_id)

    def _is_unit(self, reference: TypeRef) -> bool:
        return self._name_of(reference.base) == UNIT


# ---------------------------------------------------------------------------
# The same rule, applied to the written type expressions
# ---------------------------------------------------------------------------
#
# The proposal policy of specification section 4.3 has to decide whether a
# change of a signature breaks the contract of section 5.2, and it has to
# decide it from the documents, before the project is compiled. The rule below
# is the one of :class:`TypeEnvironment`, applied to the type *expressions*
# instead of the resolved identifiers.
#
# SDL types are nominal and there is no inheritance between them, so the name
# of a type is its identity: two named types are assignable only when they are
# the same name. A type expression the parser cannot read is not assignable to
# anything, so a change the policy cannot understand is treated as breaking
# rather than as safe.


def assignable_expressions(source: str, target: str) -> bool:
    """Whether the source type expression is assignable to the target one.

    ``source`` is assignable to ``target`` when a value of the source type may
    be used where the target type is expected, per Core 0.2 section 6.7. An
    expression that cannot be parsed is assignable to nothing.
    """
    if not isinstance(source, str) or not isinstance(target, str):
        return False
    try:
        source_expression = sdl_types.parse(source)
        target_expression = sdl_types.parse(target)
    except sdl_types.TypeSyntaxError:
        return False
    return _assignable_expression(source_expression, target_expression, set())


def is_optional_expression(text: str) -> bool:
    """Whether a type expression is an ``Optional<T>``."""
    if not isinstance(text, str):
        return False
    try:
        expression = sdl_types.parse(text)
    except sdl_types.TypeSyntaxError:
        return False
    return _is_optional_expression(expression)


def _is_optional_expression(expression: sdl_types.TypeExpr) -> bool:
    return isinstance(expression, sdl_types.TypeGeneric) and expression.name == OPTIONAL


def _is_unit_expression(expression: sdl_types.TypeExpr) -> bool:
    return isinstance(expression, sdl_types.TypeName) and expression.name == UNIT


def _assignable_expression(
    source: sdl_types.TypeExpr,
    target: sdl_types.TypeExpr,
    seen: set[tuple[str, str]],
) -> bool:
    """The rules of :meth:`TypeEnvironment._assignable`, on expressions."""
    # T is assignable to T.
    if isinstance(source, sdl_types.TypeName) and isinstance(target, sdl_types.TypeName):
        return source.name == target.name

    # Unit is not assignable to any other type.
    if _is_unit_expression(source):
        return _is_unit_expression(target)

    # T is assignable to T | U.
    if isinstance(target, sdl_types.TypeUnion):
        return any(_assignable_expression(source, member, seen) for member in target.items)

    # T | U is assignable to V if both T and U are assignable to V.
    if isinstance(source, sdl_types.TypeUnion):
        return all(_assignable_expression(member, target, seen) for member in source.items)

    # T is assignable to Optional<T>.
    if isinstance(source, sdl_types.TypeName) and _is_optional_expression(target):
        return _assignable_expression(source, target.args[0], seen) if target.args else True

    # Optional<T> is assignable to Optional<U> if T is assignable to U.
    if _is_optional_expression(source) and _is_optional_expression(target):
        if not source.args or not target.args:
            return False
        return _assignable_expression(source.args[0], target.args[0], seen)

    if isinstance(source, sdl_types.TypeGeneric) and isinstance(target, sdl_types.TypeGeneric):
        if source.name != target.name:
            return False
        if len(source.args) != len(target.args):
            return False
        key = (source.name, target.name)
        if key in seen:
            return False
        seen = seen | {key}

        if source.name in INVARIANT:
            # List<T> and Map<K,V> are invariant.
            return all(
                _identical_expression(a, b) for a, b in zip(source.args, target.args)
            )
        if source.name in COVARIANT:
            # Result<T,E> is covariant in T and E.
            return all(
                _assignable_expression(a, b, seen) for a, b in zip(source.args, target.args)
            )
        return all(
            _identical_expression(a, b) for a, b in zip(source.args, target.args)
        )

    return False


def _identical_expression(left: sdl_types.TypeExpr, right: sdl_types.TypeExpr) -> bool:
    """Whether two type expressions are structurally the same."""
    if isinstance(left, sdl_types.TypeName) and isinstance(right, sdl_types.TypeName):
        return left.name == right.name
    if isinstance(left, sdl_types.TypeGeneric) and isinstance(right, sdl_types.TypeGeneric):
        return (
            left.name == right.name
            and len(left.args) == len(right.args)
            and all(_identical_expression(a, b) for a, b in zip(left.args, right.args))
        )
    if isinstance(left, sdl_types.TypeUnion) and isinstance(right, sdl_types.TypeUnion):
        return len(left.items) == len(right.items) and all(
            any(_identical_expression(item, other) for other in right.items)
            for item in left.items
        )
    return False
