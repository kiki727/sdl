"""Referential validation of a proposal.

Specification section 8.4, phase two: *checks if all new IDs and references in
``value`` fields exist in the current specification or are defined within the
same proposal*.
"""

from __future__ import annotations

from dataclasses import dataclass

from sdl.documents import DocumentSet
from sdl.proposal.models import Patch, PatchAction, Proposal
from sdl.proposal.paths import (
    _MISSING,
    TargetError,
    parent_of,
    parse_target,
    resolve,
    select_document,
)
from sdl.types import expressions as sdl_types


@dataclass
class ReferenceViolation:
    """A reference in a proposal that does not resolve."""

    code: str
    message: str


def known_names(documents: DocumentSet) -> set[str]:
    """Every name the current specification declares."""
    names: set[str] = set(sdl_types.BUILTINS)
    for document in documents.documents.values():
        root = document.root
        if not isinstance(root, dict):
            continue
        identifier = root.get("id")
        if isinstance(identifier, str):
            names.add(identifier)
        for method in root.get("methods") or []:
            if isinstance(method, dict) and isinstance(method.get("id"), str):
                names.add(method["id"])
        for step in root.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("id"), str):
                names.add(step["id"])
        for declaration in root.get("types") or []:
            if isinstance(declaration, dict) and isinstance(declaration.get("id"), str):
                names.add(declaration["id"])
        if document.kind == "types":
            names.update(name for name in root if isinstance(name, str))
    return names


def introduced_names(proposal: Proposal) -> set[str]:
    """The names a proposal introduces itself."""
    names: set[str] = set()
    for patch in proposal.patches:
        if patch.action != PatchAction.ADD:
            continue
        value = patch.value
        if isinstance(value, dict):
            identifier = value.get("id")
            if isinstance(identifier, str):
                names.add(identifier)
            interface = value.get("interface")
            if isinstance(interface, str):
                names.add(interface)
            implementation = value.get("implementation")
            if isinstance(implementation, str):
                names.add(implementation)
    return names


def _type_names(expression: str) -> list[str]:
    try:
        parsed = sdl_types.parse(expression)
    except sdl_types.TypeSyntaxError:
        return []
    return [name.name for name in sdl_types.walk(parsed) if isinstance(name, sdl_types.TypeName)]


def _target_problem(documents: DocumentSet, patch: Patch) -> str | None:
    """The reason why the target of a patch does not resolve, or None.

    Specification section 8.4, phase two: a proposal may only change an
    element of the specification that exists. A target that names nothing is
    a referential failure, not a policy failure.
    """
    try:
        target = parse_target(patch.target)
    except TargetError:
        # The syntax of the target is reported by the caller.
        return None

    document = select_document(documents, target)
    if document is None:
        return f"The target {patch.target!r} does not name a document of the project."

    root = document.root
    if root is None:
        return f"The document {document.relative!r} has no root to patch."

    current = resolve(root, target.segments)
    if current is not _MISSING:
        if patch.action == PatchAction.ADD and not isinstance(current, (dict, list)):
            return (
                f"The target {patch.target!r} already exists and is not a collection, "
                f"so nothing can be added to it."
            )
        return None

    if patch.action == PatchAction.ADD:
        # The target may be new, but the collection that receives it has to
        # exist.
        container, _ = parent_of(root, target.segments)
        if container is _MISSING:
            return (
                f"The target {patch.target!r} does not exist, so nothing can be added "
                f"to it."
            )
        return None

    return f"The target {patch.target!r} does not exist."


def check(proposal: Proposal, documents: DocumentSet) -> list[ReferenceViolation]:
    """Check every reference of a proposal."""
    violations: list[ReferenceViolation] = []
    known = known_names(documents)
    introduced = introduced_names(proposal)

    for patch in proposal.patches:
        try:
            parse_target(patch.target)
        except Exception as error:  # noqa: BLE001 - reported as a violation
            violations.append(
                ReferenceViolation(code="SDL-E701", message=str(error))
            )
            continue

        problem = _target_problem(documents, patch)
        if problem is not None:
            violations.append(
                ReferenceViolation(code="SDL-E701", message=problem)
            )
            continue

        value = patch.value
        if value is None:
            continue

        if isinstance(value, dict):
            for key in ("interface", "implementation"):
                name = value.get(key)
                if isinstance(name, str) and name not in known and name not in introduced:
                    violations.append(
                        ReferenceViolation(
                            code="SDL-E702",
                            message=(
                                f"The patch of {patch.target!r} refers to {name!r}, "
                                f"which does not exist in the specification and is not "
                                f"introduced by this proposal."
                            ),
                        )
                    )
            identifier = value.get("id")
            if (
                isinstance(identifier, str)
                and patch.action == PatchAction.REPLACE
                and identifier not in known
                and identifier not in introduced
            ):
                violations.append(
                    ReferenceViolation(
                        code="SDL-E702",
                        message=(
                            f"The patch of {patch.target!r} refers to {identifier!r}, "
                            f"which does not exist in the specification."
                        ),
                    )
                )
            expression = value.get("type")
            if isinstance(expression, str):
                violations.extend(
                    _check_type_expression(expression, known, introduced, patch)
                )
            for key in ("output", "outputs"):
                declared = value.get(key)
                if isinstance(declared, str):
                    violations.extend(
                        _check_type_expression(declared, known, introduced, patch)
                    )

    return violations


def _check_type_expression(
    expression: str,
    known: set[str],
    introduced: set[str],
    patch: Patch,
) -> list[ReferenceViolation]:
    violations: list[ReferenceViolation] = []
    for name in _type_names(expression):
        if name in known or name in introduced:
            continue
        violations.append(
            ReferenceViolation(
                code="SDL-E702",
                message=(
                    f"The patch of {patch.target!r} refers to the type {name!r}, "
                    f"which does not exist in the specification."
                ),
            )
        )
    return violations
