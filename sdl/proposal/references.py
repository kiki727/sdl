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


#: The keys whose value names an element of the specification: a reference
#: that has to resolve, not a declaration.
_NAME_KEYS = frozenset({"interface", "implementation"})

#: The keys whose value is a type expression, or a mapping of them.
_TYPE_KEYS = frozenset(
    {"type", "output", "outputs", "input", "inputs", "fields", "properties"}
)


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
    """The names a proposal introduces itself.

    A name is introduced when a patch *declares* it: the value of an ``add``
    carries the ``id`` of the element. The ``interface`` and the
    ``implementation`` of a binding are *references*, not declarations, so
    they are not introduced here. A proposal that binds an interface it does
    not declare is a broken reference of phase two, not a new name.
    """
    names: set[str] = set()
    for patch in proposal.patches:
        if patch.action != PatchAction.ADD:
            continue
        value = patch.value
        if isinstance(value, dict):
            identifier = value.get("id")
            if isinstance(identifier, str):
                names.add(identifier)
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
            target = parse_target(patch.target)
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

        # A whole element that replaces an existing one names the element it
        # replaces, so the identifier it carries has to exist already.
        if patch.action == PatchAction.REPLACE and isinstance(value, dict):
            identifier = value.get("id")
            if (
                isinstance(identifier, str)
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

        # Every reference inside the value, however deeply it is nested. The
        # last segment of the target says what the value as a whole is: a name
        # (``bindings[Greeter].implementation``), a type or a mapping of types
        # (``methods[greet].outputs``, ``Greeting.fields``), or a structure to
        # look inside.
        last = target.segments[-1].value if target.segments else ""
        if last in _NAME_KEYS and isinstance(value, str):
            violations.extend(_check_name(value, known, introduced, patch))
        elif last in _TYPE_KEYS:
            violations.extend(_check_types(value, known, introduced, patch))
        else:
            violations.extend(_check_value(value, known, introduced, patch))

    return violations


def _check_value(
    value: object,
    known: set[str],
    introduced: set[str],
    patch: Patch,
) -> list[ReferenceViolation]:
    """Every reference inside the value of a patch.

    A value is a structure the patch writes into the specification. The keys
    it uses say what the strings under them mean: an ``interface`` or an
    ``implementation`` names an element, an ``inputs`` or a ``fields`` maps a
    name to a type, and anything else is a structure to look inside.
    """
    violations: list[ReferenceViolation] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _NAME_KEYS and isinstance(item, str):
                violations.extend(_check_name(item, known, introduced, patch))
            elif key in _TYPE_KEYS:
                violations.extend(_check_types(item, known, introduced, patch))
            else:
                violations.extend(_check_value(item, known, introduced, patch))
    elif isinstance(value, list):
        for item in value:
            violations.extend(_check_value(item, known, introduced, patch))
    return violations


def _check_types(
    item: object,
    known: set[str],
    introduced: set[str],
    patch: Patch,
) -> list[ReferenceViolation]:
    """A value that holds a type expression, or a mapping of them.

    An ``output`` object and an inference object carry the type under the
    ``type`` key; any other mapping maps a name to a type.
    """
    violations: list[ReferenceViolation] = []
    if isinstance(item, str):
        violations.extend(_check_type_expression(item, known, introduced, patch))
    elif isinstance(item, dict):
        declared = item.get("type")
        if isinstance(declared, str) and (len(item) == 1 or "origin" in item):
            violations.extend(
                _check_type_expression(declared, known, introduced, patch)
            )
        else:
            for nested in item.values():
                violations.extend(_check_types(nested, known, introduced, patch))
    elif isinstance(item, list):
        for nested in item:
            violations.extend(_check_types(nested, known, introduced, patch))
    return violations


def _check_name(
    name: str,
    known: set[str],
    introduced: set[str],
    patch: Patch,
) -> list[ReferenceViolation]:
    """A name a patch writes that has to name an element of the specification."""
    if name in known or name in introduced:
        return []
    return [
        ReferenceViolation(
            code="SDL-E702",
            message=(
                f"The patch of {patch.target!r} refers to {name!r}, which does "
                f"not exist in the specification and is not introduced by this "
                f"proposal."
            ),
        )
    ]


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
