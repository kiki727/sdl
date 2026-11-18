"""End to end tests: from an SDL document to the canonical IR.

These tests cover the chain that no unit test can: validate, parse, lower,
resolve, and firewall. They are the reason the pipeline exists at all.
"""

from __future__ import annotations

import hashlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sdl.compiler import compile_project
from sdl.ir import serialization
from sdl.ir.edges import EdgeKind
from sdl.ir.symbols import (
    FlowStepSymbol,
    FlowSymbol,
    ImplementationSymbol,
    InterfaceSymbol,
    MethodSymbol,
    ModuleSymbol,
    ProjectSymbol,
)

EXAMPLES = REPO_ROOT / "examples"
PAYMENT = EXAMPLES / "payment_system" / "project.sdl.yaml"
HERO = EXAMPLES / "hero_site" / "project.sdl.yaml"
FIXTURES = Path(__file__).parent / "fixtures"


def _compile(entry: Path):
    result = compile_project(entry)
    assert result.ok, result.report.as_dict()
    return result


def _digest(result) -> str:
    return hashlib.sha256(serialization.dumps(result.graph).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The pipeline runs
# ---------------------------------------------------------------------------


def test_payment_system_compiles() -> None:
    """The payment example compiles into a valid IR."""
    result = _compile(PAYMENT)
    assert result.symbol_count > 0
    assert result.edge_count > 0
    assert len(result.documents) == 6


def test_hero_site_compiles() -> None:
    """The hero site example compiles into a valid IR."""
    result = _compile(HERO)
    assert result.symbol_count > 0
    assert len(result.documents) == 7


# ---------------------------------------------------------------------------
# M5 - the IR is reproducible
# ---------------------------------------------------------------------------


def test_the_ir_is_deterministic() -> None:
    """The same document always produces the same IR, byte for byte."""
    for entry in (PAYMENT, HERO):
        digests = {_digest(_compile(entry)) for _ in range(3)}
        assert len(digests) == 1, f"{entry.name} produced {len(digests)} different IRs"


def test_the_ir_serialises_deterministically() -> None:
    """The serialisation of one graph is stable."""
    result = _compile(PAYMENT)
    assert serialization.dumps(result.graph) == serialization.dumps(result.graph)


def test_the_resolver_is_repeatable() -> None:
    """Resolving the same graph twice reproduces it, byte for byte.

    The Semantic Firewall re-derives the references of a patched graph, so the
    resolver must remove and rebuild its edges without losing what it learned
    the first time — in particular the shape of a type expression, which the
    resolved identifier alone does not keep.
    """
    from sdl.lowering.resolver import SymbolResolver

    result = _compile(PAYMENT)
    before = serialization.dumps(result.graph)

    unresolved = SymbolResolver(result.graph).resolve_all()

    assert not unresolved, [item.message for item in unresolved]
    assert serialization.dumps(result.graph) == before, "the resolver is not repeatable"


# ---------------------------------------------------------------------------
# M4 - nothing is lost
# ---------------------------------------------------------------------------


def test_the_project_keeps_its_configuration() -> None:
    """The constraints, the bindings and the backend survive the lowering."""
    result = _compile(PAYMENT)
    projects = [
        symbol
        for symbol in result.graph.symbols.values()
        if isinstance(symbol, ProjectSymbol)
    ]
    assert len(projects) == 1
    project = projects[0]

    constraints = project.metadata["constraints"]["forbidden_imports"]
    assert constraints, "the forbidden imports were lost"
    assert constraints[0]["from"] == "payment_demo_system"
    assert constraints[0]["deny"] == ["legacy_payment_module"]

    bindings = project.metadata["bindings"]
    assert bindings[0]["interface"] == "PaymentProvider"
    assert bindings[0]["implementation"] == "stripe_provider_impl"

    assert project.metadata["backend"]["target"] == "python"
    assert project.metadata["backend"]["mode"] == "codegen"
    assert project.metadata["imports"], "the imports were lost"


def test_the_interface_keeps_its_methods_and_invariants() -> None:
    """The methods and the invariants of an interface survive the lowering."""
    result = _compile(PAYMENT)
    interfaces = [
        symbol
        for symbol in result.graph.symbols.values()
        if isinstance(symbol, InterfaceSymbol)
    ]
    assert len(interfaces) == 1
    interface = interfaces[0]

    assert interface.invariants == ["amount > 0"]
    assert interface.metadata["method_ids"], "the methods were lost"

    methods = [
        symbol
        for symbol in result.graph.symbols.values()
        if isinstance(symbol, MethodSymbol) and symbol.qualified_name.startswith("PaymentProvider::")
    ]
    assert len(methods) == 1
    method = methods[0]
    assert [parameter.name for parameter in method.parameters] == ["request"]
    assert method.return_type_id is not None


def test_the_flow_keeps_its_outputs_and_error_handling() -> None:
    """The outputs and the error handling of a flow survive the lowering."""
    result = _compile(PAYMENT)
    flows = [symbol for symbol in result.graph.symbols.values() if isinstance(symbol, FlowSymbol)]
    assert len(flows) == 1
    flow = flows[0]

    assert flow.metadata["outputs"] == {"success": "Boolean", "tx_id": "UUID"}
    assert flow.metadata["output_mapping"]["success"] == "payment_result.success"
    assert flow.metadata["step_order"], "the step order was lost"

    steps = [
        symbol for symbol in result.graph.symbols.values() if isinstance(symbol, FlowStepSymbol)
    ]
    assert len(steps) == 2
    on_errors = {step.metadata.get("on_error") for step in steps}
    assert "fail" in on_errors, "the error handling strategy was lost"


def test_the_implementation_keeps_its_source() -> None:
    """The source location of an implementation survives the lowering."""
    result = _compile(PAYMENT)
    implementations = [
        symbol
        for symbol in result.graph.symbols.values()
        if isinstance(symbol, ImplementationSymbol)
    ]
    assert len(implementations) == 1
    implementation = implementations[0]
    assert implementation.language == "python"
    assert implementation.source_file == "src/payments/stripe_api.py"
    assert implementation.source_symbol == "StripePaymentProvider"
    assert implementation.metadata["implements_list"] == ["PaymentProvider"]


def test_the_module_and_its_function_survive() -> None:
    """A module and the functions it declares survive the lowering."""
    result = _compile(PAYMENT)
    modules = [
        symbol for symbol in result.graph.symbols.values() if isinstance(symbol, ModuleSymbol)
    ]
    assert len(modules) == 1
    assert modules[0].name == "payment_helper"

    functions = [
        symbol
        for symbol in result.graph.symbols.values()
        if isinstance(symbol, MethodSymbol)
        and symbol.qualified_name == "payment_helper::build_request"
    ]
    assert len(functions) == 1
    assert sorted(parameter.name for parameter in functions[0].parameters) == ["amount", "token"]


def test_the_flow_state_is_typed() -> None:
    """Every variable of the Flow State must have a resolved type."""
    result = _compile(PAYMENT)
    flow = [
        symbol for symbol in result.graph.symbols.values() if isinstance(symbol, FlowSymbol)
    ][0]

    names = set(flow.state_definitions)
    assert names == {"order_id", "amount", "token", "request", "payment_result"}

    for name, variable in flow.state_definitions.items():
        assert variable.type_id, f"{name} has no type"
        symbol = result.graph.get_symbol(variable.type_id)
        assert symbol is not None, f"{name} refers to an unknown type"


# ---------------------------------------------------------------------------
# The relations of the IR
# ---------------------------------------------------------------------------


def test_the_reference_edges_are_built() -> None:
    """The resolver derives the reference edges of the IR."""
    result = _compile(PAYMENT)
    kinds = {edge.kind for edge in result.graph.edges.values()}
    for expected in (
        EdgeKind.CONTAINS,
        EdgeKind.IMPLEMENTS,
        EdgeKind.CALLS,
        EdgeKind.RETURNS,
        EdgeKind.HAS_PARAMETER,
        EdgeKind.HAS_STEP,
        EdgeKind.NEXT,
        EdgeKind.BINDS_TO,
    ):
        assert expected in kinds, f"the {expected.name} relation is missing"


def test_the_project_contains_every_project_scoped_symbol() -> None:
    """The project is the root of the graph."""
    result = _compile(PAYMENT)
    project = [
        symbol for symbol in result.graph.symbols.values() if isinstance(symbol, ProjectSymbol)
    ][0]

    contained = {
        edge.target
        for edge in result.graph.get_edges_from(project.id)
        if edge.kind == EdgeKind.CONTAINS
    }
    for symbol in result.graph.symbols.values():
        if symbol.id == project.id:
            continue
        if symbol.metadata.get("builtin"):
            continue
        if "::" in symbol.qualified_name:
            continue
        assert symbol.id in contained, f"{symbol.qualified_name} is not contained by the project"


# ---------------------------------------------------------------------------
# The firewall sees the whole IR
# ---------------------------------------------------------------------------


def test_a_broken_call_is_rejected() -> None:
    """A flow that calls something that does not exist must not compile."""
    result = compile_project(FIXTURES / "broken_call" / "project.sdl.yaml")
    assert not result.ok
    codes = {diagnostic.code for diagnostic in result.report.errors}
    assert "SDL-E511" in codes, result.report.as_dict()


# ---------------------------------------------------------------------------
# The proposal protocol on a real project
# ---------------------------------------------------------------------------


def _proposal(patches, approve: bool = False):
    from sdl.proposal.models import Patch, PatchAction, Proposal

    return Proposal(
        id="p_test",
        target_version="1.0.0",
        author="test",
        rationale="an integration test proposal",
        patches=[
            Patch(target=target, action=PatchAction.REPLACE, value=value)
            for target, value in patches
        ],
        approve=approve,
    )


@contextmanager
def project_copy():
    """A temporary copy of the payment example.

    A proposal merges into the documents, so a test must never run against
    the example in the repository.
    """
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(prefix="sdl-integration-") as directory:
        target = Path(directory) / "payment_system"
        shutil.copytree(PAYMENT.parent, target)
        yield target / "project.sdl.yaml"


def _snapshot(root: Path) -> dict[str, bytes]:
    """The bytes of every document of the project."""
    return {
        path.name: path.read_bytes()
        for path in sorted(root.glob("*.sdl.yaml"))
    }


def test_a_proposal_that_breaks_a_reference_is_rejected() -> None:
    """A proposal that points a call at a symbol that does not exist is rejected."""
    from sdl.proposal.engine import ProposalEngine

    with project_copy() as entry:
        before = entry.parent.joinpath("flow.sdl.yaml").read_text(encoding="utf-8")

        result = ProposalEngine(entry).process_proposal(
            _proposal([("flow.sdl.yaml:steps[create_request].call", "Missing::Method")])
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert "SDL-E511" in result.codes(), result.codes()
        after = entry.parent.joinpath("flow.sdl.yaml").read_text(encoding="utf-8")
        assert after == before, "the document was modified"


def test_a_proposal_that_breaks_a_type_is_rejected() -> None:
    """A proposal that changes the type of a state variable is rejected."""
    from sdl.proposal.engine import ProposalEngine

    with project_copy() as entry:
        result = ProposalEngine(entry).process_proposal(
            _proposal([("flow.sdl.yaml:inputs.amount", "String")])
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert "SDL-E501" in result.codes(), result.codes()


def test_a_valid_proposal_is_not_merged_without_approval() -> None:
    """A valid proposal without the approval of section 8.5 is not merged."""
    from sdl.proposal.engine import ProposalEngine

    with project_copy() as entry:
        before = entry.parent.joinpath("flow.sdl.yaml").read_text(encoding="utf-8")

        result = ProposalEngine(entry).process_proposal(
            _proposal([("flow.sdl.yaml:version", "1.1.0")], approve=False)
        )

        assert result.accepted, f"the proposal was rejected: {result.message}"
        assert not result.merged, "the proposal was merged without an approval"
        after = entry.parent.joinpath("flow.sdl.yaml").read_text(encoding="utf-8")
        assert after == before, "the document was modified"


def test_an_approved_proposal_is_merged_and_stays_valid() -> None:
    """An approved proposal is merged, and the project stays valid."""
    from sdl.compiler import compile_project
    from sdl.proposal.engine import ProposalEngine

    with project_copy() as entry:
        result = ProposalEngine(entry).process_proposal(
            _proposal([("flow.sdl.yaml:version", "1.1.0")], approve=True)
        )

        assert result.accepted, f"the proposal was rejected: {result.message}"
        assert result.merged, "the proposal was not merged"

        flow = entry.parent.joinpath("flow.sdl.yaml").read_text(encoding="utf-8")
        assert 'version: "1.1.0"' in flow, flow

        compilation = compile_project(entry)
        assert compilation.ok, compilation.report.as_dict()


def test_a_failed_merge_rolls_back_every_document() -> None:
    """A merge that fails half way leaves no document changed.

    The merge is a transaction over the documents. If a replacement fails
    after another one succeeded, the documents that were already replaced
    must be restored, and the proposal must report that it did not merge.
    """
    import unittest.mock

    from sdl.proposal.engine import ProposalEngine

    with project_copy() as entry:
        before = _snapshot(entry.parent)
        real_replace = os.replace
        calls = {"count": 0}

        def flaky_replace(source, destination):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("the disk is full")
            return real_replace(source, destination)

        with unittest.mock.patch("sdl.proposal.engine.os.replace", flaky_replace):
            result = ProposalEngine(entry).process_proposal(
                _proposal(
                    [
                        ("flow.sdl.yaml:version", "1.1.0"),
                        ("types.sdl.yaml:PaymentResponse.version", "1.1.0"),
                    ],
                    approve=True,
                )
            )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert not result.merged, "a failed merge reported success"
        assert result.phase == "merge", result.phase
        assert "SDL-E705" in result.codes(), result.codes()
        assert _snapshot(entry.parent) == before, "the documents were modified"


CHECKS = [
    test_payment_system_compiles,
    test_hero_site_compiles,
    test_the_ir_is_deterministic,
    test_the_ir_serialises_deterministically,
    test_the_resolver_is_repeatable,
    test_the_project_keeps_its_configuration,
    test_the_interface_keeps_its_methods_and_invariants,
    test_the_flow_keeps_its_outputs_and_error_handling,
    test_the_implementation_keeps_its_source,
    test_the_module_and_its_function_survive,
    test_the_flow_state_is_typed,
    test_the_reference_edges_are_built,
    test_the_project_contains_every_project_scoped_symbol,
    test_a_broken_call_is_rejected,
    test_a_proposal_that_breaks_a_reference_is_rejected,
    test_a_proposal_that_breaks_a_type_is_rejected,
    test_a_valid_proposal_is_not_merged_without_approval,
    test_an_approved_proposal_is_merged_and_stays_valid,
    test_a_failed_merge_rolls_back_every_document,
]


def run_all() -> bool:
    print("=== SDL PIPELINE INTEGRATION TEST ===")
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
