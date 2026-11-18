"""The proposal engine.

Specification section 8.4 defines four validation phases, and section 8.5
the acceptance and the merge:

    PROPOSAL
      -> phase 1  syntactic validation
      -> phase 2  referential validation
      -> phase 3  policy check
      -> phase 4  semantic simulation
      -> approval
      -> merge

Phase one is the validation of the proposal document itself, which the command
line performs before it hands the proposal to the engine. Phases two to four
run here.

Phase four builds a *virtual* version of the specification: the patches are
applied to a shadow copy of the document set, the copy is written out, and the
whole pipeline runs on it — schema, semantics, lowering, resolution and the
Semantic Firewall. A virtual specification that breaks a rule is rejected.

The merge writes the changed documents back and increments the project version
according to semver.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sdl.diagnostics import Diagnostic
from sdl.documents import DocumentSet, load_document_set
from sdl.proposal import references
from sdl.proposal.document_patcher import (
    DocumentPatchError,
    DocumentPatcher,
    PatchConflictError,
)
from sdl.proposal.models import Patch, Proposal
from sdl.proposal.policy import PolicyChecker, PolicyViolation
from sdl.proposal.policy import (
    _collect_contracts,
    _collect_ids,
    _collect_signatures,
    _collect_versions,
    _signature_breaks,
)

#: The phases of specification section 8.4, in order.
PHASES = ("syntactic", "referential", "policy", "semantic")


@dataclass
class ProposalResult:
    """The outcome of a proposal."""

    accepted: bool = False
    merged: bool = False
    phase: str | None = None
    message: str = ""
    violations: list[PolicyViolation] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    def codes(self) -> set[str]:
        return {diagnostic.code for diagnostic in self.diagnostics}


class ProposalEngine:
    """Runs a proposal through the validation phases and merges it."""

    def __init__(self, entry: Path, current_version: str | None = None):
        self.entry = Path(entry).resolve()
        self.root = self.entry.parent
        self.current_version = current_version

    # -- entry points --------------------------------------------------------

    def process_proposal(self, proposal: Proposal) -> ProposalResult:
        """Run a proposal through the phases."""
        try:
            documents = load_document_set(self.entry)
        except OSError as error:
            return ProposalResult(message=f"Cannot read the project: {error}")

        result = ProposalResult()

        # The proposal must be based on the current version of the project.
        current = self._project_version(documents)
        if current is not None and proposal.target_version != current:
            result.phase = "referential"
            result.message = (
                f"The proposal is based on version {proposal.target_version}, but the "
                f"project is at version {current}."
            )
            result.diagnostics = [
                Diagnostic(
                    phase="proposal",
                    severity="error",
                    code="SDL-E703",
                    message=result.message,
                    file=proposal.id,
                )
            ]
            return result

        # Phase 2: referential validation.
        violations = references.check(proposal, documents)
        if violations:
            result.phase = "referential"
            result.message = "The proposal refers to elements that do not exist."
            result.diagnostics = [
                Diagnostic(
                    phase="proposal",
                    severity="error",
                    code=violation.code,
                    message=violation.message,
                    file=proposal.id,
                )
                for violation in violations
            ]
            return result

        # Phase 3: the policy of specification section 4.3.
        policy = self._policy(documents)
        checker = PolicyChecker(policy)
        shadow = documents.clone()
        try:
            DocumentPatcher(shadow).apply_patches(proposal.patches)
        except DocumentPatchError as error:
            result.phase = "policy"
            result.message = str(error)
            result.diagnostics = [
                Diagnostic(
                    phase="proposal",
                    severity="error",
                    code=(
                        "SDL-E704"
                        if isinstance(error, PatchConflictError)
                        else "SDL-E701"
                    ),
                    message=str(error),
                    file=proposal.id,
                )
            ]
            return result

        violations = checker.check(documents, shadow, proposal)
        if violations:
            result.phase = "policy"
            result.message = "The proposal violates the policy of the project."
            result.violations = violations
            result.diagnostics = [
                Diagnostic(
                    phase="proposal",
                    severity="error",
                    code=violation.code,
                    message=violation.message,
                    file=proposal.id,
                )
                for violation in violations
            ]
            return result

        # Phase 4: the semantic simulation.
        result = self._simulate(shadow, proposal)
        if not result.accepted:
            return result

        result.changed = [document.relative for document in shadow.changed()]

        # Section 8.5: the final acceptance is performed by an administrator.
        if not proposal.approve:
            result.accepted = True
            result.merged = False
            result.message = (
                "The proposal is valid but has not been approved. Nothing was merged."
            )
            return result

        try:
            self._merge(shadow, documents)
        except MergeError as error:
            result.accepted = False
            result.merged = False
            result.phase = "merge"
            result.message = str(error)
            result.diagnostics = [
                Diagnostic(
                    phase="proposal",
                    severity="error",
                    code="SDL-E705",
                    message=str(error),
                    file=proposal.id,
                )
            ]
            return result

        result.accepted = True
        result.merged = True
        result.message = "Proposal accepted and merged successfully."
        return result

    # -- phases --------------------------------------------------------------

    def _simulate(self, shadow: DocumentSet, proposal: Proposal) -> ProposalResult:
        """Build the virtual specification and run the pipeline on it."""
        from sdl.compiler import compile_project
        from sdl.document import load_schemas, validate_path

        result = ProposalResult()
        schemas = load_schemas()

        with tempfile.TemporaryDirectory(prefix="sdl-proposal-") as temporary:
            virtual_root = Path(temporary)
            virtual_entry = self._write_shadow(shadow, virtual_root)

            report = validate_path(virtual_entry, schemas)
            if report.status == "failed":
                result.phase = "semantic"
                result.message = "The virtual specification violates the specification."
                result.diagnostics = list(report.diagnostics)
                return result

            compilation = compile_project(virtual_entry, schemas=schemas)
            if not compilation.ok:
                result.phase = "semantic"
                result.message = "The virtual specification violates the specification."
                result.diagnostics = list(compilation.report.diagnostics)
                return result

        result.accepted = True
        result.phase = None
        result.message = "The virtual specification is valid."
        return result

    # -- merge ---------------------------------------------------------------

    def _merge(self, shadow: DocumentSet, original: DocumentSet) -> None:
        """Write the changed documents back and increment the version.

        The merge is a transaction. The new text of every document is written
        to a temporary file first, then every target is replaced, and if one
        of the replacements fails the documents that were already replaced are
        restored from the bytes read before the merge began. A proposal never
        leaves a half merged document set behind.
        """
        changed = list(shadow.changed())
        project = shadow.project

        if changed and project is not None:
            next_version = _next_version(original, shadow)
            if next_version is not None:
                project.root["version"] = next_version
                if project.path not in {document.path for document in changed}:
                    changed.append(project)

        if not changed:
            # Nothing changed, so there is nothing to write and the version of
            # the project must not move.
            return

        writes = {document.path: document.render() for document in changed}
        _write_atomically(writes)

    # -- helpers -------------------------------------------------------------

    def _write_shadow(self, shadow: DocumentSet, root: Path) -> Path:
        """Write the shadow documents into a directory.

        The code of the implementations is copied as well. Without it the
        virtual specification could not be checked against the contracts of
        section 5, because the realization of an implementation is code, not
        specification.
        """
        for relative, document in shadow.documents.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(document.render(), encoding="utf-8")

        for relative, source in self._implementation_sources(shadow):
            target = root / relative
            origin = self.root / source
            if not origin.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(origin.read_bytes())

        return root / self.entry.name

    @staticmethod
    def _implementation_sources(documents: DocumentSet) -> list[tuple[str, str]]:
        """The source files the implementations of a project declare."""
        found: list[tuple[str, str]] = []
        for document in documents.documents.values():
            if document.kind != "implementation":
                continue
            root = document.root
            if not isinstance(root, dict):
                continue
            source = root.get("source")
            if not isinstance(source, dict):
                continue
            file = source.get("file")
            if isinstance(file, str) and file:
                found.append((file, file))
        return found

    @staticmethod
    def _policy(documents: DocumentSet) -> dict[str, Any]:
        project = documents.project
        if project is None:
            return {}
        root = project.root
        if not isinstance(root, dict):
            return {}
        policy = root.get("policy")
        return policy if isinstance(policy, dict) else {}

    @staticmethod
    def _project_version(documents: DocumentSet) -> str | None:
        project = documents.project
        if project is None:
            return None
        root = project.root
        if not isinstance(root, dict):
            return None
        version = root.get("version")
        return version if isinstance(version, str) else None


class MergeError(Exception):
    """A merge that could not be written to the documents."""


def _write_atomically(writes: dict[Path, str]) -> None:
    """Replace every target, or restore every target that was replaced.

    The files are written and flushed before any of them is replaced, so the
    windows in which a failure can leave a half written file are as small as
    the platform allows. If a replacement fails, the bytes of the targets that
    were already replaced are restored.
    """
    prepared: list[tuple[Path, Path]] = []
    try:
        for target, text in writes.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".sdl-merge-", suffix=".tmp", dir=str(target.parent)
            )
            prepared.append((target, Path(temporary)))
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
    except OSError as error:
        _remove_temporary(prepared)
        raise MergeError(f"The merge could not be prepared: {error}") from error

    backups: dict[Path, bytes | None] = {}
    replaced: list[Path] = []
    try:
        for target, temporary in prepared:
            backups[target] = target.read_bytes() if target.is_file() else None
            os.replace(temporary, target)
            replaced.append(target)
    except OSError as error:
        for target in reversed(replaced):
            try:
                original = backups[target]
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(original)
            except OSError:
                # The rollback is best effort; the diagnostic still reports
                # that the merge did not complete.
                pass
        _remove_temporary(prepared)
        raise MergeError(f"The merge could not be written: {error}") from error


def _remove_temporary(prepared: list[tuple[Path, Path]]) -> None:
    """Remove the temporary files of a merge that did not finish."""
    for _, temporary in prepared:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _next_version(original: DocumentSet, shadow: DocumentSet) -> str | None:
    """The next version of a project, according to semver.

    Specification section 8.5: the project version is incremented according to
    semver rules, for example MAJOR when the proposal introduced a breaking
    change. A change that only touches the body of a component is a PATCH, a
    change that adds or removes a component is a MINOR, and a change that
    breaks a contract is a MAJOR.
    """
    project = shadow.project
    if project is None:
        return None
    root = project.root
    if not isinstance(root, dict):
        return None
    current = root.get("version")
    if not isinstance(current, str):
        return None
    parts = current.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    major, minor, patch = (int(part) for part in parts)

    breaking = _breaks_a_contract(original, shadow)

    before_ids: set[str] = set()
    for identifiers in _collect_ids(original).values():
        before_ids |= identifiers
    after_ids: set[str] = set()
    for identifiers in _collect_ids(shadow).values():
        after_ids |= identifiers
    added_or_removed = before_ids != after_ids

    # A component that is versioned differently is a change of the
    # specification, not only of a body.
    versioned_changed = _collect_versions(original) != _collect_versions(shadow)

    if breaking:
        return f"{major + 1}.0.0"
    if added_or_removed or versioned_changed:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _breaks_a_contract(original: DocumentSet, shadow: DocumentSet) -> bool:
    """Whether a change breaks a contract of the specification.

    A method that disappears from an interface breaks every implementation
    of it, and an interface or a type that disappears breaks every client.
    Specification section 5.4 calls such a change a breaking change, and
    section 8.5 gives it a MAJOR version.
    """
    before_signatures = _collect_signatures(original)
    after_signatures = _collect_signatures(shadow)

    # A method that is gone.
    if set(before_signatures) - set(after_signatures):
        return True

    # A method whose signature changed in a way that breaks the contract. A
    # compatible change (an added optional parameter, a widened input, a
    # narrowed output) does not break a contract and is not a MAJOR change.
    for key, signature in before_signatures.items():
        other = after_signatures.get(key)
        if other is not None and other != signature and _signature_breaks(*signature, *other):
            return True

    # An interface or a type that is gone.
    before_contracts = _collect_contracts(original)
    after_contracts = _collect_contracts(shadow)
    return bool(before_contracts - after_contracts)
