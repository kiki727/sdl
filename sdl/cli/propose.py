"""The ``propose`` command: run a proposal through the governance engine.

    python -m sdl propose examples/hero_site/proposal.sdl.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from sdl.cli.reporting import print_diagnostics
from sdl.diagnostics import Diagnostic
from sdl.document import load_schemas, validate_path
from sdl.parser.ast import ASTProposal
from sdl.parser.yaml_parser import SDLYamlParser, SDLParserError
from sdl.proposal.engine import ProposalEngine
from sdl.proposal.models import MigrationEntry, Patch, PatchAction, Proposal


def read_proposal(path: Path) -> Proposal:
    """Read a proposal document into a proposal."""
    parser = SDLYamlParser(path.name)
    try:
        ast = parser.parse(path.read_text(encoding="utf-8"))
    except (OSError, SDLParserError) as error:
        raise ValueError(f"Cannot read the proposal {path.name}: {error}") from error

    if not isinstance(ast, ASTProposal):
        raise ValueError(f"{path.name} is not a proposal document.")

    patches = [
        Patch(
            target=patch.target,
            action=PatchAction.from_string(patch.action),
            value=patch.value,
        )
        for patch in ast.patches
    ]

    migration = [
        MigrationEntry(type=entry.type, documents=list(entry.documents))
        for entry in ast.migration
    ]

    return Proposal(
        id=ast.id,
        target_version=ast.target_version,
        author=ast.author,
        rationale=ast.rationale,
        patches=patches,
        migration=migration,
    )


def approve(path: Path) -> bool:
    """Whether a proposal document carries the approval of section 8.5."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return False
    if not isinstance(data, dict):
        return False
    root = data.get("proposal")
    if not isinstance(root, dict):
        return False
    return root.get("approve") is True


def _project_entry(path: Path) -> Path | None:
    """The project document a proposal belongs to.

    The kind is read from the envelope, not searched for as a substring: a
    proposal may mention ``kind: project`` in its rationale and must not be
    mistaken for the root document.
    """
    for candidate in sorted(path.parent.glob("*.sdl.yaml")):
        if candidate == path:
            continue
        try:
            data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and data.get("kind") == "project":
            return candidate
    return None


def _payload(
    *,
    proposal_id: str,
    accepted: bool,
    merged: bool,
    phase: str | None,
    message: str,
    changed: list[str],
    diagnostics: list[Diagnostic],
) -> dict:
    """The machine readable outcome of a proposal."""
    return {
        "proposal": proposal_id,
        "accepted": accepted,
        "merged": merged,
        "phase": phase,
        "message": message,
        "changed": list(changed),
        "diagnostics": [diagnostic.as_dict() for diagnostic in diagnostics],
    }


def propose(path: Path, as_json: bool = False) -> int:
    """Run a proposal through the governance engine."""
    path = Path(path)
    if not path.exists():
        print(f"{path}: no such file", file=sys.stderr)
        return 2

    # Phase 1: the proposal document itself must be valid.
    report = validate_path(path, load_schemas())
    if report.status == "failed":
        if as_json:
            print(
                json.dumps(
                    _payload(
                        proposal_id=path.stem,
                        accepted=False,
                        merged=False,
                        phase="syntactic",
                        message="The proposal document is not valid.",
                        changed=[],
                        diagnostics=list(report.diagnostics),
                    ),
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print("PROPOSAL REJECTED")
            print("phase: syntactic")
            print_diagnostics(report)
        return 1

    try:
        proposal = read_proposal(path)
    except ValueError as error:
        diagnostic = Diagnostic(
            phase="proposal",
            severity="error",
            code="SDL-E700",
            message=str(error),
            file=path.name,
        )
        if as_json:
            print(
                json.dumps(
                    _payload(
                        proposal_id=path.stem,
                        accepted=False,
                        merged=False,
                        phase="syntactic",
                        message=str(error),
                        changed=[],
                        diagnostics=[diagnostic],
                    ),
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print_diagnostics([diagnostic])
        return 1

    proposal.approve = approve(path)

    entry = _project_entry(path)
    if entry is None:
        message = (
            f"No project document found next to {path.name}. A proposal must be "
            f"run against the project it belongs to."
        )
        if as_json:
            print(
                json.dumps(
                    _payload(
                        proposal_id=proposal.id,
                        accepted=False,
                        merged=False,
                        phase=None,
                        message=message,
                        changed=[],
                        diagnostics=[],
                    ),
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(message, file=sys.stderr)
        return 2

    result = ProposalEngine(entry).process_proposal(proposal)

    if as_json:
        print(
            json.dumps(
                _payload(
                    proposal_id=proposal.id,
                    accepted=result.accepted,
                    merged=result.merged,
                    phase=result.phase,
                    message=result.message,
                    changed=result.changed,
                    diagnostics=result.diagnostics,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif not result.accepted:
        print("PROPOSAL REJECTED")
        print(f"phase: {result.phase}")
        print(result.message)
        print_diagnostics(result.diagnostics)
    else:
        print("PROPOSAL ACCEPTED")
        print(result.message)
        if result.changed:
            print("changed documents:")
            for relative in result.changed:
                print(f"  {relative}")

    return 0 if result.accepted else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a proposal through the governance engine.")
    parser.add_argument("proposal", help="the proposal document")
    parser.add_argument("--json", action="store_true", help="emit a machine readable summary")
    args = parser.parse_args(argv)
    return propose(Path(args.proposal), args.json)


if __name__ == "__main__":
    raise SystemExit(main())
