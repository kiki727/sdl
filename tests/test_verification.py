"""Self-checks for the proposal protocol.

The proposal protocol is the governance guarantee of Core 1.0. It is defined
by specification sections 4.3, 8.2, 8.3, 8.4 and 8.5.

The checks below run against a real project on disk, because the protocol
operates on the documents: a proposal is applied to a shadow copy of the
document set, the copy is validated, and only an approved proposal is merged
back.

The module runs under pytest and, if pytest is not installed, standalone::

    python tests/test_verification.py
"""

from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdl.proposal.engine import ProposalEngine
from sdl.proposal.models import Patch, PatchAction, Proposal

PROJECT = '''sdl: "1.0"
kind: project

project:
  id: test_project
  version: "1.0.0"

  imports:
    - path: "types.sdl.yaml"
    - path: "interfaces.sdl.yaml"
    - path: "flow.sdl.yaml"
    - path: "helper.sdl.yaml"
    - path: "database.sdl.yaml"
    - path: "greeter.sdl.yaml"
    - path: "greeter_implementation.sdl.yaml"
    - path: "greeter_implementation_v2.sdl.yaml"
    - path: "payment_implementation.sdl.yaml"

  bindings:
    - interface: Greeter
      version: "1.0.0"
      implementation: greeter_impl
    - interface: PaymentProvider
      version: "1.0.0"
      implementation: payment_impl

  policy:
    forbidden_id_changes: true
    disallow_breaking_changes: true

  constraints:
    forbidden_imports:
      - from: helper
        deny:
          - database
        reason: "The helper must not reach into the database."
'''

TYPES = '''sdl: "1.0"
kind: types

types:
  PaymentRequest:
    id: PaymentRequest
    version: "1.0.0"
    fields:
      amount: Decimal

  PaymentResponse:
    id: PaymentResponse
    version: "1.0.0"
    fields:
      success: Boolean
      tx_id: UUID
'''

INTERFACES = '''sdl: "1.0"
kind: interface

interface:
  id: PaymentProvider
  version: "1.0.0"
  imports:
    - path: "types.sdl.yaml"

  methods:
    - id: charge
      version: "1.0.0"
      inputs:
        amount: Decimal
      outputs:
        type: PaymentResponse
'''

FLOW = '''sdl: "1.0"
kind: flow

flow:
  id: test_flow
  version: "1.0.0"
  imports:
    - path: "interfaces.sdl.yaml"
    - path: "types.sdl.yaml"

  inputs:
    amount: Decimal

  steps:
    - id: charge
      call: PaymentProvider::charge
      mapping:
        amount: amount
      output_map:
        result_value: result

  outputs:
    ok: Boolean

  output_mapping:
    ok: result_value.success
'''

GREETER = '''sdl: "1.0"
kind: interface

interface:
  id: Greeter
  version: "1.0.0"
  methods:
    - id: greet
      version: "1.0.0"
      inputs:
        name: String
      outputs:
        type: String
'''

GREETER_IMPLEMENTATION = '''sdl: "1.0"
kind: implementation

implementation:
  id: greeter_impl
  version: "1.0.0"
  implements:
    - interface: Greeter
      version: "1.0.0"
  language: python
  source:
    file: "src/greeter.py"
    symbol: Greeter
'''

GREETER_IMPLEMENTATION_V2 = '''sdl: "1.0"
kind: implementation

implementation:
  id: greeter_impl_v2
  version: "1.0.0"
  implements:
    - interface: Greeter
      version: "1.0.0"
  language: python
  source:
    file: "src/greeter_v2.py"
    symbol: GreeterV2
'''

PAYMENT_IMPLEMENTATION = '''sdl: "1.0"
kind: implementation

implementation:
  id: payment_impl
  version: "1.0.0"
  implements:
    - interface: PaymentProvider
      version: "1.0.0"
  language: python
  source:
    file: "src/payment.py"
    symbol: PaymentProvider
'''

HELPER = '''sdl: "1.0"
kind: module

module:
  id: helper
  functions:
    - id: helper_function
      version: "1.0.0"
      output:
        type: String
'''

DATABASE = '''sdl: "1.0"
kind: module

module:
  id: database
  functions:
    - id: query
      version: "1.0.0"
      output:
        type: String
'''

GREETER_SOURCE = '''"""The realization of the SDL interface Greeter."""


class Greeter:
    """Greets a person by name."""

    def greet(self, name: str) -> str:
        return f"Hello, {name}!"
'''

GREETER_V2_SOURCE = '''"""A second realization of the SDL interface Greeter."""


class GreeterV2:
    """Greets a person by name, in another way."""

    def greet(self, name: str) -> str:
        return f"Hi, {name}!"
'''

PAYMENT_SOURCE = '''"""The realization of the SDL interface PaymentProvider."""

from decimal import Decimal


class PaymentProvider:
    """Charges a request and reports the transaction."""

    def charge(self, amount: Decimal) -> PaymentResponse:
        return PaymentResponse(success=True, tx_id="tx")
'''

#: The Python realizations of the implementations of the temporary project.
#: The compatibility checker reads them, so a signature the project declares
#: must have a source that matches it.
SOURCES = {
    "src/greeter.py": GREETER_SOURCE,
    "src/greeter_v2.py": GREETER_V2_SOURCE,
    "src/payment.py": PAYMENT_SOURCE,
}

DOCUMENTS = {
    "project.sdl.yaml": PROJECT,
    "greeter.sdl.yaml": GREETER,
    "greeter_implementation.sdl.yaml": GREETER_IMPLEMENTATION,
    "greeter_implementation_v2.sdl.yaml": GREETER_IMPLEMENTATION_V2,
    "payment_implementation.sdl.yaml": PAYMENT_IMPLEMENTATION,
    "types.sdl.yaml": TYPES,
    "interfaces.sdl.yaml": INTERFACES,
    "flow.sdl.yaml": FLOW,
    "helper.sdl.yaml": HELPER,
    "database.sdl.yaml": DATABASE,
}


@contextmanager
def project():
    """A temporary project to run proposals against."""
    with tempfile.TemporaryDirectory(prefix="sdl-proposal-test-") as directory:
        root = Path(directory)
        for name, content in DOCUMENTS.items():
            (root / name).write_text(content, encoding="utf-8")
        for name, content in SOURCES.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        yield root / "project.sdl.yaml"


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(root.glob("*.sdl.yaml"))
    }


def _proposal(patches: list[Patch], approve: bool = False) -> Proposal:
    return Proposal(
        id="p_test",
        target_version="1.0.0",
        author="test",
        rationale="a test proposal",
        patches=patches,
        approve=approve,
    )


def _run(entry: Path, proposal: Proposal):
    return ProposalEngine(entry).process_proposal(proposal)


# ---------------------------------------------------------------------------
# V01 - a rejected proposal changes nothing
# ---------------------------------------------------------------------------


def test_v01_rejected_proposal_changes_nothing() -> None:
    """A rejected proposal must leave every document byte for byte as it was."""
    with project() as entry:
        before = _snapshot(entry.parent)

        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="types.sdl.yaml:PaymentResponse.id",
                        action=PatchAction.REPLACE,
                        value="Renamed",
                    )
                ]
            ),
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert _snapshot(entry.parent) == before, "the documents were modified"


# ---------------------------------------------------------------------------
# V02 - the protocol is deterministic
# ---------------------------------------------------------------------------


def test_v02_the_same_proposal_gives_the_same_result() -> None:
    """Running the same proposal twice must give the same verdict."""
    with project() as entry:
        patch = Patch(
            target="flow.sdl.yaml:steps[charge].call",
            action=PatchAction.REPLACE,
            value="Ghost::Method",
        )
        first = _run(entry, _proposal([patch]))
        second = _run(entry, _proposal([patch]))

        assert first.accepted == second.accepted
        assert first.phase == second.phase
        assert first.codes() == second.codes()


# ---------------------------------------------------------------------------
# V03 - an unresolvable target is rejected
# ---------------------------------------------------------------------------


def test_v03_unresolvable_target_is_rejected() -> None:
    """A patch whose target does not exist is rejected."""
    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="flow.sdl.yaml:steps[nonexistent].call",
                        action=PatchAction.REPLACE,
                        value="Something",
                    )
                ]
            ),
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"


# ---------------------------------------------------------------------------
# V04 - an architectural prohibition is enforced
# ---------------------------------------------------------------------------


def test_v04_forbidden_import_is_rejected() -> None:
    """A proposal that introduces a forbidden import is rejected."""
    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="helper.sdl.yaml:imports",
                        action=PatchAction.ADD,
                        value=[{"module": "database"}],
                    )
                ]
            ),
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert "SDL-E601" in result.codes(), result.codes()


# ---------------------------------------------------------------------------
# V05 - a type mismatch is rejected
# ---------------------------------------------------------------------------


def test_v05_type_mismatch_is_rejected() -> None:
    """A proposal that gives a state variable the wrong type is rejected."""
    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="flow.sdl.yaml:inputs.amount",
                        action=PatchAction.REPLACE,
                        value="String",
                    )
                ]
            ),
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert "SDL-E501" in result.codes(), result.codes()


# ---------------------------------------------------------------------------
# V06 - conflicting patches are rejected
# ---------------------------------------------------------------------------


def test_v06_conflicting_patches_are_rejected() -> None:
    """Two patches that name the same element are rejected.

    The two targets are written differently — one by file, one by kind — but
    they select the same document and the same pointer. The identity of a
    target is canonical, not textual, so the conflict is detected.
    """
    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="flow.sdl.yaml:version",
                        action=PatchAction.REPLACE,
                        value="1.1.0",
                    ),
                    Patch(
                        target="flow.test_flow.version",
                        action=PatchAction.REPLACE,
                        value="1.2.0",
                    ),
                ]
            ),
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert result.phase == "policy", result.phase
        assert "SDL-E704" in result.codes(), result.codes()


# ---------------------------------------------------------------------------
# V07 - a stale proposal is rejected
# ---------------------------------------------------------------------------


def test_v07_stale_version_is_rejected() -> None:
    """A proposal based on an older version of the project is rejected."""
    with project() as entry:
        proposal = _proposal(
            [
                Patch(
                    target="flow.sdl.yaml:version",
                    action=PatchAction.REPLACE,
                    value="1.1.0",
                )
            ]
        )
        proposal.target_version = "0.9.0"

        result = _run(entry, proposal)

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert "SDL-E703" in result.codes(), result.codes()


# ---------------------------------------------------------------------------
# V08 - a broken reference is rejected
# ---------------------------------------------------------------------------


def test_v08_broken_reference_is_rejected() -> None:
    """A proposal that points a call at a symbol that does not exist is rejected."""
    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="flow.sdl.yaml:steps[charge].call",
                        action=PatchAction.REPLACE,
                        value="Ghost::Method",
                    )
                ]
            ),
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert "SDL-E511" in result.codes(), result.codes()


# ---------------------------------------------------------------------------
# V09 - the policy of specification section 4.3
# ---------------------------------------------------------------------------


def test_v09_identifier_changes_are_rejected() -> None:
    """A proposal that changes an identifier is rejected by the policy."""
    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="types.sdl.yaml:PaymentResponse.id",
                        action=PatchAction.REPLACE,
                        value="Renamed",
                    )
                ]
            ),
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert "SDL-E602" in result.codes(), result.codes()


def test_v10_breaking_changes_are_rejected() -> None:
    """A proposal that changes a signature without a version bump is rejected."""
    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="interfaces.sdl.yaml:methods[charge].outputs.type",
                        action=PatchAction.REPLACE,
                        value="String",
                    )
                ]
            ),
        )

        assert not result.accepted, f"the proposal was accepted: {result.message}"
        assert "SDL-E602" in result.codes(), result.codes()


# ---------------------------------------------------------------------------
# V11 - the approval of specification section 8.5
# ---------------------------------------------------------------------------


def test_v11_a_valid_proposal_is_not_merged_without_approval() -> None:
    """A valid proposal without an approval must not change anything."""
    with project() as entry:
        before = _snapshot(entry.parent)

        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="flow.sdl.yaml:version",
                        action=PatchAction.REPLACE,
                        value="1.1.0",
                    )
                ],
                approve=False,
            ),
        )

        assert result.accepted, f"the proposal was rejected: {result.message}"
        assert not result.merged, "the proposal was merged without an approval"
        assert _snapshot(entry.parent) == before, "the documents were modified"


def test_v12_an_approved_proposal_is_merged() -> None:
    """An approved proposal is merged and the project version is incremented."""
    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="flow.sdl.yaml:version",
                        action=PatchAction.REPLACE,
                        value="1.1.0",
                    )
                ],
                approve=True,
            ),
        )

        assert result.accepted, f"the proposal was rejected: {result.message}"
        assert result.merged, "the proposal was not merged"

        flow = (entry.parent / "flow.sdl.yaml").read_text(encoding="utf-8")
        assert 'version: "1.1.0"' in flow, flow

        project_text = (entry.parent / "project.sdl.yaml").read_text(encoding="utf-8")
        assert 'version: "1.1.0"' in project_text, project_text


def test_v13_a_merged_proposal_stays_valid() -> None:
    """A merged proposal must leave the project in a valid state."""
    from sdl.compiler import compile_project

    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="flow.sdl.yaml:version",
                        action=PatchAction.REPLACE,
                        value="1.1.0",
                    )
                ],
                approve=True,
            ),
        )
        assert result.merged, result.message

        compilation = compile_project(entry)
        assert compilation.ok, compilation.report.as_dict()


def test_v14_a_binding_is_addressed_by_its_interface() -> None:
    """A binding is named by the interface it binds.

    Specification section 8.2 gives ``project.bindings[PaymentProvider]`` as
    the example of a target, so that form has to work.
    """
    from sdl.proposal.models import Patch, PatchAction

    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="project.bindings[Greeter].implementation",
                        action=PatchAction.REPLACE,
                        value="greeter_impl_v2",
                    )
                ],
                approve=True,
            ),
        )

        assert result.accepted, result.message
        bindings = (entry.parent / "project.sdl.yaml").read_text(encoding="utf-8")
        assert "greeter_impl_v2" in bindings, bindings


def test_v15_an_add_to_a_list_appends_an_element() -> None:
    """``add`` adds an element to a list, it does not replace the list.

    Specification section 8.3: ``add`` *adds a new element to a list or a
    new field to an object*. The example of section 8.2 adds a module to
    the imports of a module, so the form has to work.
    """
    from sdl.documents import load_document_set
    from sdl.proposal.document_patcher import DocumentPatcher
    from sdl.proposal.models import Patch, PatchAction

    with project() as entry:
        documents = load_document_set(entry)
        shadow = documents.clone()
        before = len(shadow.project.root["bindings"])

        DocumentPatcher(shadow).apply_patches(
            [
                Patch(
                    target="project.bindings",
                    action=PatchAction.ADD,
                    value={
                        "interface": "Greeter",
                        "version": "2.0.0",
                        "implementation": "greeter_impl_v2",
                    },
                )
            ]
        )

        after = shadow.project.root["bindings"]
        assert len(after) == before + 1, after
        assert after[-1]["implementation"] == "greeter_impl_v2", after


def test_v16_a_breaking_change_needs_a_major_version() -> None:
    """A change of a signature increments the major version of the interface.

    Specification section 5.4: a change that breaks a signature must
    increment the MAJOR version of the interface. A patch version is not
    enough.
    """
    from sdl.proposal.models import Patch, PatchAction

    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="interfaces.sdl.yaml:methods[charge].inputs",
                        action=PatchAction.REPLACE,
                        value={"amount": "Decimal", "currency": "String"},
                    ),
                    Patch(
                        target="interfaces.sdl.yaml:version",
                        action=PatchAction.REPLACE,
                        value="1.0.1",
                    ),
                ],
                approve=True,
            ),
        )

        assert not result.accepted, "the proposal was accepted"
        assert result.phase == "policy", result.phase
        assert "SDL-E602" in result.codes(), result.codes()


def test_v17_a_target_that_does_not_exist_is_a_referential_failure() -> None:
    """A target that names nothing fails in the second phase.

    Specification section 8.4: the referential validation is the second
    phase, the policy check is the third. A target that resolves to nothing
    is a referential failure.
    """
    from sdl.proposal.models import Patch, PatchAction

    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="nowhere.sdl.yaml:Greeting.fields",
                        action=PatchAction.REPLACE,
                        value={"message": "String"},
                    )
                ],
                approve=True,
            ),
        )

        assert not result.accepted, "the proposal was accepted"
        assert result.phase == "referential", result.phase
        assert "SDL-E701" in result.codes(), result.codes()


def test_v18_a_call_without_a_binding_is_rejected() -> None:
    """A project that binds no implementation for a called interface is invalid.

    Specification section 6.2, rule three: a call is resolved through the
    bindings table.
    """
    from sdl.proposal.models import Patch, PatchAction

    with project() as entry:
        result = _run(
            entry,
            _proposal(
                [
                    Patch(
                        target="project.bindings[PaymentProvider]",
                        action=PatchAction.REMOVE,
                        value=None,
                    )
                ],
                approve=True,
            ),
        )

        assert not result.accepted, "the proposal was accepted"
        assert result.phase == "semantic", result.phase
        assert "SDL-E603" in result.codes(), result.codes()


CHECKS = [
    test_v01_rejected_proposal_changes_nothing,
    test_v02_the_same_proposal_gives_the_same_result,
    test_v03_unresolvable_target_is_rejected,
    test_v04_forbidden_import_is_rejected,
    test_v05_type_mismatch_is_rejected,
    test_v06_conflicting_patches_are_rejected,
    test_v07_stale_version_is_rejected,
    test_v08_broken_reference_is_rejected,
    test_v09_identifier_changes_are_rejected,
    test_v10_breaking_changes_are_rejected,
    test_v11_a_valid_proposal_is_not_merged_without_approval,
    test_v12_an_approved_proposal_is_merged,
    test_v13_a_merged_proposal_stays_valid,
    test_v14_a_binding_is_addressed_by_its_interface,
    test_v15_an_add_to_a_list_appends_an_element,
    test_v16_a_breaking_change_needs_a_major_version,
    test_v17_a_target_that_does_not_exist_is_a_referential_failure,
    test_v18_a_call_without_a_binding_is_rejected,
]


def run_all() -> bool:
    print("=== SDL PROPOSAL PROTOCOL SELF-CHECK ===")
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
