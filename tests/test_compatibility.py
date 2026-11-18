"""Tests of the compatibility engine of specification section 5.

The engine checks that an implementation really satisfies the interface it
declares: the completeness of section 5.3.1, the signature compatibility of
section 5.2, and the version compatibility of section 5.4.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sdl.compiler import compile_project
from sdl.types.semver import satisfies

FIXTURES = Path(__file__).parent / "fixtures" / "compatibility"
VALID = FIXTURES / "valid"
INVALID = FIXTURES / "invalid"
WIDE = FIXTURES / "wide"
GENERIC = FIXTURES / "generic"
PERMISSIVE = FIXTURES / "permissive"
UNANNOTATED = FIXTURES / "unannotated"
MISSING_SOURCE = FIXTURES / "missing_source"


def _messages(result) -> str:
    return " ".join(diagnostic.message for diagnostic in result.report.errors)


# ---------------------------------------------------------------------------
# The implementations
# ---------------------------------------------------------------------------


def test_a_compatible_implementation_is_accepted() -> None:
    """An implementation that satisfies the contract is accepted."""
    result = compile_project(VALID / "project.sdl.yaml")
    assert result.ok, result.report.as_dict()


def test_an_implementation_that_accepts_more_is_accepted() -> None:
    """An implementation may accept more than the contract asks for.

    Specification section 5.2, input contravariance: the input of the
    contract must be assignable to the input the implementation accepts. An
    implementation that accepts ``Optional<Decimal>`` accepts every
    ``Decimal`` the contract can send, so it satisfies the contract.

    The identifier of a type is a digest and not its name, so the rule of
    the optional has to be resolved through the graph. A fixture whose
    identifier is the name would make the rule pass for the wrong reason.
    """
    result = compile_project(WIDE / "project.sdl.yaml")
    assert result.ok, result.report.as_dict()


def test_the_input_contravariance_is_enforced() -> None:
    """An implementation must accept at least what the contract asks for."""
    result = compile_project(INVALID / "project.sdl.yaml")
    assert not result.ok
    messages = _messages(result)
    assert "does not accept the Decimal" in messages, messages


def test_the_output_covariance_is_enforced() -> None:
    """An implementation must return at most what the contract promises."""
    result = compile_project(INVALID / "project.sdl.yaml")
    assert not result.ok
    messages = _messages(result)
    assert "not assignable to the PaymentResponse" in messages, messages


def test_a_generic_return_type_is_compatible() -> None:
    """The arguments of a generic are preserved and compared.

    The contract returns ``Result<PaymentResponse, Error>``. A comparison
    that dropped the arguments would accept any ``Result``, and the resolver
    must keep the shape of the return type for the rule to mean anything.
    """
    result = compile_project(GENERIC / "project.sdl.yaml")
    assert result.ok, result.report.as_dict()

    methods = [
        symbol
        for symbol in result.graph.symbols.values()
        if getattr(symbol, "qualified_name", None) == "PaymentProvider::charge"
    ]
    assert len(methods) == 1
    reference = methods[0].metadata["return_type_ref"]
    assert reference.kind == "generic", reference
    assert len(reference.arguments) == 2, reference


def test_a_default_value_does_not_widen_the_parameter_type() -> None:
    """A default changes what a caller may omit, not the accepted type.

    An implementation with an extra optional parameter and an implementation
    that accepts ``**kwargs`` both accept everything the contract sends.
    """
    result = compile_project(PERMISSIVE / "project.sdl.yaml")
    assert result.ok, result.report.as_dict()


def test_an_unannotated_signature_is_rejected() -> None:
    """A signature the validator cannot read is rejected, not skipped."""
    result = compile_project(UNANNOTATED / "project.sdl.yaml")
    assert not result.ok
    codes = {diagnostic.code for diagnostic in result.report.errors}
    assert "SDL-E607" in codes, result.report.as_dict()


def test_a_missing_source_is_rejected() -> None:
    """An implementation that declares Python code that does not exist fails."""
    result = compile_project(MISSING_SOURCE / "project.sdl.yaml")
    assert not result.ok
    codes = {diagnostic.code for diagnostic in result.report.errors}
    assert "SDL-E607" in codes, result.report.as_dict()


def test_the_completeness_is_enforced() -> None:
    """An implementation must implement every method of the contract."""
    result = compile_project(INVALID / "project.sdl.yaml")
    assert not result.ok
    messages = _messages(result)
    assert "does not implement 'charge'" in messages, messages


def test_the_version_is_enforced() -> None:
    """The version of an implementation must satisfy the one it is bound to."""
    result = compile_project(INVALID / "project.sdl.yaml")
    assert not result.ok
    messages = _messages(result)
    assert "does not satisfy the version" in messages, messages


def test_every_violation_is_reported() -> None:
    """The report names every violation, not only the first one."""
    result = compile_project(INVALID / "project.sdl.yaml")
    errors = [d for d in result.report.errors if d.code == "SDL-E604"]
    assert len(errors) == 4, [d.message for d in errors]


# ---------------------------------------------------------------------------
# The version ranges of Core 0.2 section 4.5
# ---------------------------------------------------------------------------


def test_an_exact_version() -> None:
    """A requirement without an operator is that exact version."""
    assert satisfies("1.0.0", "1.0.0")
    assert not satisfies("1.0.1", "1.0.0")


def test_a_caret_range() -> None:
    """A caret range allows the changes that do not break the contract."""
    assert satisfies("1.0.0", "^1.0.0")
    assert satisfies("1.9.9", "^1.0.0")
    assert not satisfies("2.0.0", "^1.0.0")
    assert not satisfies("0.9.0", "^1.0.0")


def test_a_tilde_range() -> None:
    """A tilde range allows the changes of the minor version."""
    assert satisfies("1.0.5", "~1.0.0")
    assert not satisfies("1.1.0", "~1.0.0")


def test_a_comparator_range() -> None:
    """A range may hold several comparators."""
    assert satisfies("1.5.0", ">=1.0.0 <2.0.0")
    assert not satisfies("2.5.0", ">=1.0.0 <2.0.0")
    assert not satisfies("0.5.0", ">=1.0.0 <2.0.0")


CHECKS = [
    test_a_compatible_implementation_is_accepted,
    test_an_implementation_that_accepts_more_is_accepted,
    test_a_generic_return_type_is_compatible,
    test_a_default_value_does_not_widen_the_parameter_type,
    test_an_unannotated_signature_is_rejected,
    test_a_missing_source_is_rejected,
    test_the_input_contravariance_is_enforced,
    test_the_output_covariance_is_enforced,
    test_the_completeness_is_enforced,
    test_the_version_is_enforced,
    test_every_violation_is_reported,
    test_an_exact_version,
    test_a_caret_range,
    test_a_tilde_range,
    test_a_comparator_range,
]


def run_all() -> bool:
    print("=== SDL COMPATIBILITY TEST ===")
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
