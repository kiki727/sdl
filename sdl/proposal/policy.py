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
from sdl.types.assignability import assignable_expressions, is_optional_expression


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
    """The signature of every method, keyed by interface and method.

    The signature is the mapping of the inputs and the output type, as the
    documents write them. The mapping is kept as a mapping so that the
    compatibility of a change can be decided per parameter.
    """
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
                {str(name): str(expression) for name, expression in inputs.items()},
                output if isinstance(output, str) else None,
            )
    return signatures


def _signature_breaks(
    before_inputs: dict[str, str],
    before_output: str | None,
    after_inputs: dict[str, str],
    after_output: str | None,
    aliases_before: dict[str, str] | None = None,
    aliases_after: dict[str, str] | None = None,
) -> bool:
    """Whether a change of a signature breaks the contract of section 5.2.

    A client written against the old signature must remain valid against the
    new one. The signature breaks the contract when:

    * a parameter the client supplied is gone;
    * a parameter accepts less than it did (its old type is not assignable to
      its new one, the contravariance rule of section 5.2);
    * a parameter is added that the client cannot omit, that is one that is
      not ``Optional``;
    * the output is no longer assignable to what the client expected (the
      covariance rule of section 5.2).

    A change that only widens the accepted inputs, only narrows the output, or
    only adds optional parameters is compatible, so it is not breaking and the
    policy of section 4.3 does not require a version increment for it.

    The alias maps, when they are given, are applied to the expressions before
    the rule: an alias is transparent (section 9.3.2), so a parameter that
    only writes its type through an alias accepts the same values.
    """
    # A parameter the client supplied is gone.
    for name in before_inputs:
        if name not in after_inputs:
            return True

    # A parameter that accepts less than it did.
    for name, old in before_inputs.items():
        new = after_inputs.get(name)
        if new is None:
            continue
        if not assignable_expressions(old, new, aliases_before, aliases_after):
            return True

    # A parameter the client cannot omit.
    for name, new in after_inputs.items():
        if name in before_inputs:
            continue
        if not is_optional_expression(new, aliases_after):
            return True

    # The output the client expected is no longer produced.
    if before_output is not None:
        if after_output is None:
            return True
        if not assignable_expressions(after_output, before_output, aliases_after, aliases_before):
            return True

    return False


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


def _collect_aliases(documents: DocumentSet) -> dict[str, str]:
    """The aliases of the specification, by name.

    An alias is a type declaration whose definition is a ``type`` expression
    (section 9.3.2). The target is kept as the document writes it, so the
    expansion happens where the rule is applied.
    """
    aliases: dict[str, str] = {}
    for document in documents.documents.values():
        root = _root(document)
        if not isinstance(root, dict):
            continue
        if document.kind == "types":
            for name, declaration in root.items():
                if isinstance(declaration, dict) and isinstance(declaration.get("type"), str):
                    aliases[str(name)] = declaration["type"]
        for declaration in root.get("types") or []:
            if not isinstance(declaration, dict):
                continue
            identifier = declaration.get("id")
            target = declaration.get("type")
            if isinstance(identifier, str) and isinstance(target, str):
                aliases[identifier] = target
    return aliases


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


def _declared_migrations(proposal: Proposal) -> dict[str, set[str]]:
    """The migration plan of a proposal, by the type it covers.

    The plan is the list of entries of the proposal. Each entry names a type
    and the documents the plan migrates. An entry that names the same type
    twice adds to the coverage of that type.
    """
    declared: dict[str, set[str]] = {}
    for entry in proposal.migration:
        name = getattr(entry, "type", None)
        if not isinstance(name, str) or not name:
            continue
        documents = getattr(entry, "documents", []) or []
        declared.setdefault(name, set()).update(
            str(document) for document in documents if isinstance(document, str)
        )
    return declared


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
        aliases_before = _collect_aliases(original)
        aliases_after = _collect_aliases(patched)
        versions_before = _collect_versions(original)
        versions_after = _collect_versions(patched)

        for key, signature in sorted(before.items()):
            if key not in after:
                continue
            if after[key] == signature:
                continue
            if not _signature_breaks(
                *signature, *after[key], aliases_before, aliases_after
            ):
                # The change is compatible with the old signature, so it does
                # not break the contract and the policy does not apply.
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
        """Check the migration plan of a changed type.

        Specification section 4.3.1: when a type definition changes and the
        project requires a migration plan, the proposal must carry a plan for
        every module that depends on the type. The form of the plan is the one
        recorded in the changelog of Core 1.0: a list of entries, each one
        naming the type that changed and the documents the plan covers.
        """
        violations: list[PolicyViolation] = []
        before = _collect_types(original)
        after = _collect_types(patched)
        declared = _declared_migrations(proposal)
        known = set(original.documents)

        for name, shape in sorted(before.items()):
            if name not in after or after[name] == shape:
                continue
            dependents = _dependents(original, name)
            if not dependents:
                continue

            covered = declared.get(name)
            if covered is None:
                violations.append(
                    PolicyViolation(
                        code="SDL-E602",
                        message=(
                            f"The type {name} changes, but the proposal carries no "
                            f"migration plan for it. The policy requires a plan that "
                            f"covers every dependent module: "
                            f"{', '.join(sorted(dependents))}."
                        ),
                    )
                )
                continue

            unknown = sorted(document for document in covered if document not in known)
            if unknown:
                violations.append(
                    PolicyViolation(
                        code="SDL-E602",
                        message=(
                            f"The migration plan of the type {name} names documents "
                            f"that are not part of the project: {', '.join(unknown)}."
                        ),
                    )
                )

            missing = sorted(document for document in dependents if document not in covered)
            if missing:
                violations.append(
                    PolicyViolation(
                        code="SDL-E602",
                        message=(
                            f"The migration plan of the type {name} does not cover "
                            f"every dependent module. It is missing: "
                            f"{', '.join(missing)}."
                        ),
                    )
                )
        return violations
