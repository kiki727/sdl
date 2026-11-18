"""Tests of the assignability rules of Core 0.2 section 6.7.

These are the rules the compatibility engine of section 5.2 rests on. They are
tested directly, because a mistake in them would silently make every
signature of every implementation compatible with every contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sdl.ir.edges import EdgeKind
from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import (
    MethodSymbol,
    MethodParameter,
    SymbolId,
    SymbolKind,
    TypeKind,
    TypeRef,
    TypeSymbol,
)
from sdl.lowering.identity import symbol_id
from sdl.types.assignability import (
    TypeEnvironment,
    assignable_expressions,
    is_optional_expression,
)


def _graph() -> SymbolGraph:
    """A graph with the built-in types and two user types.

    The identifiers are the ones the lowering produces, a digest and not the
    name. A fixture whose identifier is the name would make the rules of
    section 6.7 pass for the wrong reason: the code would compare a digest
    with a name and never recognise an ``Optional``.
    """
    graph = SymbolGraph()
    for name in ("String", "Int", "Decimal", "Boolean", "Unit", "List", "Map", "Result", "Optional"):
        graph.add_symbol(
            TypeSymbol(
                id=symbol_id("type", name),
                kind=SymbolKind.TYPE,
                name=name,
                qualified_name=name,
                type_kind=TypeKind.SCALAR,
                metadata={"builtin": True},
            )
        )
    for name in ("Payment", "StripePayment"):
        graph.add_symbol(
            TypeSymbol(
                id=symbol_id("type", name),
                kind=SymbolKind.TYPE,
                name=name,
                qualified_name=name,
                type_kind=TypeKind.COMPOUND,
            )
        )
    return graph


ENV = TypeEnvironment(_graph())


def named(name: str) -> TypeRef:
    return TypeRef(kind="named", base=symbol_id("type", name))


def generic(name: str, *arguments: str) -> TypeRef:
    return TypeRef(
        kind="generic",
        base=symbol_id("type", name),
        arguments=[named(argument) for argument in arguments],
    )


def union(*members: str) -> TypeRef:
    return TypeRef(kind="union", arguments=[named(member) for member in members])


# ---------------------------------------------------------------------------
# The rules of section 6.7
# ---------------------------------------------------------------------------


def test_a_type_is_assignable_to_itself() -> None:
    """T is assignable to T."""
    assert ENV.assignable(named("Decimal"), named("Decimal"))
    assert ENV.assignable(named("Payment"), named("Payment"))


def test_a_type_is_not_assignable_to_another_one() -> None:
    """Classes and enums are nominal, and there are no implicit conversions."""
    assert not ENV.assignable(named("Payment"), named("StripePayment"))
    assert not ENV.assignable(named("StripePayment"), named("Payment"))
    assert not ENV.assignable(named("Int"), named("Decimal"))
    assert not ENV.assignable(named("String"), named("Int"))


def test_a_type_is_assignable_to_an_optional_of_it() -> None:
    """T is assignable to Optional<T>."""
    assert ENV.assignable(named("Decimal"), generic("Optional", "Decimal"))
    assert not ENV.assignable(named("Decimal"), generic("Optional", "String"))


def test_an_optional_is_assignable_to_an_optional() -> None:
    """Optional<T> is assignable to Optional<U> if T is assignable to U."""
    assert ENV.assignable(
        generic("Optional", "Decimal"), generic("Optional", "Decimal")
    )
    assert not ENV.assignable(
        generic("Optional", "Decimal"), generic("Optional", "String")
    )


def test_a_type_is_assignable_to_a_union_that_holds_it() -> None:
    """T is assignable to T | U."""
    assert ENV.assignable(named("Decimal"), union("Decimal", "String"))
    assert ENV.assignable(named("String"), union("Decimal", "String"))
    assert not ENV.assignable(named("Boolean"), union("Decimal", "String"))


def test_a_union_is_assignable_when_every_member_is() -> None:
    """T | U is assignable to V if both T and U are assignable to V."""
    assert ENV.assignable(union("Decimal", "Decimal"), named("Decimal"))
    assert not ENV.assignable(union("Decimal", "String"), named("Decimal"))


def test_a_list_is_invariant() -> None:
    """List<T> is invariant."""
    assert ENV.assignable(generic("List", "Decimal"), generic("List", "Decimal"))
    assert not ENV.assignable(generic("List", "Decimal"), generic("List", "String"))


def test_a_map_is_invariant() -> None:
    """Map<K,V> is invariant."""
    assert ENV.assignable(
        generic("Map", "String", "Decimal"), generic("Map", "String", "Decimal")
    )
    assert not ENV.assignable(
        generic("Map", "String", "Decimal"), generic("Map", "String", "String")
    )
    assert not ENV.assignable(
        generic("Map", "String", "Decimal"), generic("Map", "Int", "Decimal")
    )


def test_a_result_is_covariant() -> None:
    """Result<T,E> is covariant in T and E."""
    assert ENV.assignable(
        generic("Result", "Decimal", "String"), generic("Result", "Decimal", "String")
    )
    assert ENV.assignable(
        generic("Result", "Decimal", "String"), generic("Result", "Decimal", "String")
    )
    assert not ENV.assignable(
        generic("Result", "Decimal", "String"), generic("Result", "String", "String")
    )


def test_the_unit_type_is_assignable_to_nothing() -> None:
    """Unit is not assignable to any other type."""
    assert ENV.assignable(named("Unit"), named("Unit"))
    assert not ENV.assignable(named("Unit"), named("String"))
    assert not ENV.assignable(named("String"), named("Unit"))


def test_an_alias_is_expanded() -> None:
    """The rules apply after alias expansion."""
    graph = _graph()
    alias = TypeSymbol(
        id=symbol_id("type", "Money"),
        kind=SymbolKind.TYPE,
        name="Money",
        qualified_name="Money",
        type_kind=TypeKind.ALIAS,
        metadata={"alias_type_ref": named("Decimal")},
    )
    graph.add_symbol(alias)
    environment = TypeEnvironment(graph)

    assert environment.assignable(named("Money"), named("Decimal"))
    assert not environment.assignable(named("Money"), named("String"))


# ---------------------------------------------------------------------------
# The same rules, applied to the type expressions of the documents
# ---------------------------------------------------------------------------
#
# The proposal policy of section 4.3 decides whether a change of a signature
# breaks the contract of section 5.2 from the *documents*, before the project
# is compiled. It applies the same rules to the written type expressions.


def test_a_written_type_is_assignable_to_an_optional_of_it() -> None:
    """T is assignable to Optional<T>, on the written expressions too."""
    assert assignable_expressions("String", "Optional<String>")
    assert not assignable_expressions("Optional<String>", "String")


def test_a_written_type_is_nominal() -> None:
    """Classes are nominal, and a written type is assignable to itself only."""
    assert assignable_expressions("Payment", "Payment")
    assert not assignable_expressions("Payment", "StripePayment")
    assert not assignable_expressions("Int", "Decimal")


def test_a_written_type_is_assignable_to_a_union_that_holds_it() -> None:
    """T is assignable to T | U, and a union is assignable to V if every member is."""
    assert assignable_expressions("String", "String | Int")
    assert not assignable_expressions("Boolean", "String | Int")
    assert assignable_expressions("String | String", "String")
    assert not assignable_expressions("String | Boolean", "String | Int")


def test_a_written_generic_is_invariant_unless_it_is_a_result() -> None:
    """List and Map are invariant, Result is covariant."""
    assert assignable_expressions("List<String>", "List<String>")
    assert not assignable_expressions("List<String>", "List<Int>")
    assert assignable_expressions("Result<String, Int>", "Result<String, Int>")
    assert not assignable_expressions("Result<Int, Int>", "Result<String, Int>")


def test_a_written_expression_that_cannot_be_read_is_not_assignable() -> None:
    """A change the policy cannot understand is breaking, not safe."""
    assert not assignable_expressions("String", "String<")
    assert not assignable_expressions("nonsense", "String")
    assert not assignable_expressions("String", "Optional<")


def test_a_written_optional_is_recognised() -> None:
    """The policy asks whether an added parameter can be omitted."""
    assert is_optional_expression("Optional<String>")
    assert is_optional_expression("Optional<List<String>>")
    assert not is_optional_expression("String")
    assert not is_optional_expression("List<String>")
    assert not is_optional_expression("String<")


CHECKS = [
    test_a_type_is_assignable_to_itself,
    test_a_type_is_not_assignable_to_another_one,
    test_a_type_is_assignable_to_an_optional_of_it,
    test_an_optional_is_assignable_to_an_optional,
    test_a_type_is_assignable_to_a_union_that_holds_it,
    test_a_union_is_assignable_when_every_member_is,
    test_a_list_is_invariant,
    test_a_map_is_invariant,
    test_a_result_is_covariant,
    test_the_unit_type_is_assignable_to_nothing,
    test_an_alias_is_expanded,
    test_a_written_type_is_assignable_to_an_optional_of_it,
    test_a_written_type_is_nominal,
    test_a_written_type_is_assignable_to_a_union_that_holds_it,
    test_a_written_generic_is_invariant_unless_it_is_a_result,
    test_a_written_expression_that_cannot_be_read_is_not_assignable,
    test_a_written_optional_is_recognised,
]


def run_all() -> bool:
    print("=== SDL ASSIGNABILITY TEST ===")
    failures = 0
    for check in CHECKS:
        name = check.__name__
        try:
            check()
        except AssertionError as error:
            failures += 1
            print(f"{name} | FAIL | {error}")
        except Exception as error:  # noqa: BLE001 - a broken check must not abort the run
            failures += 1
            print(f"{name} | ERROR | {type(error).__name__}: {error}")
        else:
            print(f"{name} | PASS")
    print()
    print(f"{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    return failures == 0


if __name__ == "__main__":
    raise SystemExit(0 if run_all() else 1)
