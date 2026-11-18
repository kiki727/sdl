"""The proposal policy of specification section 4.3.

A project may declare three prohibitions:

    policy:
      disallow_breaking_changes: true
      require_migration_for_type_change: true
      forbidden_id_changes: true

They are checked during the diff phase, that is against the proposal and the
current specification, before a proposal is accepted. A violation is
``SDL-E602``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sdl.documents import DocumentSet, SourceDocument
from sdl.proposal.models import Proposal


@dataclass
class PolicyViolation:
    """One violation of the proposal policy."""

    code: str
    message: str


def _root(document: SourceDocument) -> Any:
    return document.root


def _is_major_increment(old: str, new: str) -> bool:
    """Whether a version goes up by a major step.

    Specification section 5.4: a change that breaks a signature must
    increment the MAJOR version of the interface.
    """
    from sdl.types.semver import parse_version

    before = parse_version(old)
    after = parse_version(new)
    if before is None or after is None:
        return False
    return after[0] > before[0]


def _collect_ids(documents: DocumentSet) -> dict[str, set[str]]:
    """The identifiers declared by every document, by document kind."""
    found: dict[str, set[str]] = {}
    for document in documents.documents.values():
        root = _root(document)
        identifiers: set[str] = set()
        if isinstance(root, dict):
            if isinstance(root.get("id"), str):
                identifiers.add(root["id"])
            for method in root.get("methods") or []:
                if isinstance(method, dict) and isinstance(method.get("id"), str):
                    identifiers.add(method["id"])
            for step in root.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("id"), str):
                    identifiers.add(step["id"])
            for declaration in root.get("types") or []:
                if isinstance(declaration, dict) and isinstance(declaration.get("id"), str):
                    identifiers.add(declaration["id"])
            if document.kind == "types" and isinstance(root, dict):
                for name, declaration in root.items():
                    if isinstance(declaration, dict) and isinstance(declaration.get("id"), str):
                        identifiers.add(declaration["id"])
                    elif isinstance(name, str):
                        identifiers.add(name)
        found[document.relative] = identifiers
    return found


def _collect_signatures(documents: DocumentSet) -> dict[str, tuple]:
    """The signature of every method, keyed by interface and method."""
    signatures: dict[str, tuple] = {}
    for document in documents.documents.values():
        root = _root(document)
        if not isinstance(root, dict):
            continue
        for method in root.get("methods") or []:
            if not isinstance(method, dict):
                continue
            identifier = method.get("id")
            if not isinstance(identifier, str):
                continue
            inputs = method.get("inputs")
            if not isinstance(inputs, dict):
                inputs = method.get("input")
            if not isinstance(inputs, dict):
                inputs = {}
            output = method.get("outputs")
            if isinstance(output, dict):
                output = output.get("type")
            if not isinstance(output, str):
                output = method.get("output")
                if isinstance(output, dict):
                    output = output.get("type")
            key = f"{root.get('id', document.relative)}::{identifier}"
            signatures[key] = (
                tuple(sorted((str(k), str(v)) for k, v in inputs.items())),
                output if isinstance(output, str) else None,
            )
    return signatures


def _collect_contracts(documents: DocumentSet) -> set[str]:
    """The interfaces and the types the specification declares.

    They are the contracts of the system: a client depends on them, so
    removing one of them breaks the clients.
    """
    contracts: set[str] = set()
    for document in documents.documents.values():
        root = _root(document)
        if not isinstance(root, dict):
            continue
        if document.kind == "interface":
            identifier = root.get("id")
            if isinstance(identifier, str):
                contracts.add(identifier)
        if document.kind == "types":
            contracts.update(name for name in root if isinstance(name, str))
        for declaration in root.get("types") or []:
            if isinstance(declaration, dict) and isinstance(declaration.get("id"), str):
                contracts.add(declaration["id"])
    return contracts


def _collect_versions(documents: DocumentSet) -> dict[str, str]:
    """The version of every versioned component."""
    versions: dict[str, str] = {}
    for document in documents.documents.values():
        root = _root(document)
        if not isinstance(root, dict):
            continue
        identifier = root.get("id")
        if isinstance(identifier, str) and isinstance(root.get("version"), str):
            versions[identifier] = root["version"]
    return versions


def _collect_types(documents: DocumentSet) -> dict[str, tuple]:
    """The fields of every type, keyed by type name."""
    types: dict[str, tuple] = {}
    for document in documents.documents.values():
        root = _root(document)
        if not isinstance(root, dict):
            continue
        if document.kind == "types":
            for name, declaration in root.items():
                if isinstance(declaration, dict):
                    types[name] = _type_shape(declaration)
        for declaration in root.get("types") or []:
            if isinstance(declaration, dict) and isinstance(declaration.get("id"), str):
                types[declaration["id"]] = _type_shape(declaration)
    return types


def _type_shape(declaration: dict[str, Any]) -> tuple:
    fields = declaration.get("fields")
    shape = tuple(sorted((str(k), str(v)) for k, v in fields.items())) if isinstance(fields, dict) else ()
    return (shape, declaration.get("type"), tuple(declaration.get("enum") or ()))


def _dependents(documents: DocumentSet, type_name: str) -> set[str]:
    """The documents that depend on a type."""
    dependents: set[str] = set()
    for document in documents.documents.values():
        root = _root(document)
        if not isinstance(root, dict):
            continue
        used = False
        for method in root.get("methods") or []:
            if not isinstance(method, dict):
                continue
            inputs = method.get("inputs") if isinstance(method.get("inputs"), dict) else method.get("input")
            values = list(inputs.values()) if isinstance(inputs, dict) else []
            output = method.get("outputs")
            if isinstance(output, dict):
                output = output.get("type")
            if isinstance(output, str):
                values.append(output)
            if any(type_name in str(value) for value in values):
                used = True
        for declaration in root.get("types") or []:
            if isinstance(declaration, dict) and declaration.get("id") == type_name:
                used = False
        if used:
            dependents.add(document.relative)
    return dependents


class PolicyChecker:
    """Checks a proposal against the policy of the project."""

    def __init__(self, policy: dict[str, Any] | None):
        self.policy = policy or {}

    @property
    def disallow_breaking_changes(self) -> bool:
        return bool(self.policy.get("disallow_breaking_changes", False))

    @property
    def require_migration_for_type_change(self) -> bool:
        return bool(self.policy.get("require_migration_for_type_change", False))

    @property
    def forbidden_id_changes(self) -> bool:
        return bool(self.policy.get("forbidden_id_changes", False))

    def check(
        self,
        original: DocumentSet,
        patched: DocumentSet,
        proposal: Proposal,
    ) -> list[PolicyViolation]:
        """Check the proposal against the policy."""
        violations: list[PolicyViolation] = []

        if self.forbidden_id_changes:
            violations.extend(self._check_id_changes(original, patched))

        if self.disallow_breaking_changes:
            violations.extend(self._check_breaking_changes(original, patched))

        if self.require_migration_for_type_change:
            violations.extend(self._check_migrations(original, patched, proposal))

        return violations

    # -- rules ---------------------------------------------------------------

    def _check_id_changes(
        self,
        original: DocumentSet,
        patched: DocumentSet,
    ) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []
        before = _collect_ids(original)
        after = _collect_ids(patched)
        for relative, identifiers in sorted(before.items()):
            removed = identifiers - after.get(relative, set())
            if removed:
                violations.append(
                    PolicyViolation(
                        code="SDL-E602",
                        message=(
                            f"The proposal removes the identifier "
                            f"{', '.join(sorted(removed))} from {relative}. The policy "
                            f"forbids changing the identifiers of existing components."
                        ),
                    )
                )
        return violations

    def _check_breaking_changes(
        self,
        original: DocumentSet,
        patched: DocumentSet,
    ) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []
        before = _collect_signatures(original)
        after = _collect_signatures(patched)
        versions_before = _collect_versions(original)
        versions_after = _collect_versions(patched)

        for key, signature in sorted(before.items()):
            if key not in after:
                continue
            if after[key] == signature:
                continue
            interface = key.split("::", 1)[0]
            old_version = versions_before.get(interface)
            new_version = versions_after.get(interface)
            if old_version is not None and new_version is not None and new_version != old_version:
                # The interface was versioned. Section 5.4 requires a breaking
                # change to increment the MAJOR version, so a smaller step is
                # not enough.
                if _is_major_increment(old_version, new_version):
                    continue
                violations.append(
                    PolicyViolation(
                        code="SDL-E602",
                        message=(
                            f"The signature of {key} changes, but the version of the "
                            f"interface {interface} goes from {old_version} to "
                            f"{new_version}. A breaking change must increment the major "
                            f"version of the interface."
                        ),
                    )
                )
                continue
            violations.append(
                PolicyViolation(
                    code="SDL-E602",
                    message=(
                        f"The signature of {key} changes, but the version of the "
                        f"interface {interface} does not. The policy forbids breaking "
                        f"changes without a version increment."
                    ),
                )
            )
        return violations

    def _check_migrations(
        self,
        original: DocumentSet,
        patched: DocumentSet,
        proposal: Proposal,
    ) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []
        before = _collect_types(original)
        after = _collect_types(patched)

        touched = {patch.target for patch in proposal.patches}

        for name, shape in sorted(before.items()):
            if name not in after or after[name] == shape:
                continue
            dependents = _dependents(original, name)
            if not dependents:
                continue
            covered = any(
                any(relative in target for target in touched)
                for relative in dependents
            )
            if covered:
                continue
            violations.append(
                PolicyViolation(
                    code="SDL-E602",
                    message=(
                        f"The type {name} changes, but the proposal does not touch the "
                        f"documents that depend on it: {', '.join(sorted(dependents))}. "
                        f"The policy requires a migration plan for every dependent module."
                    ),
                )
            )
        return violations
