"""Run every check in the repository.

    python tests/run_all.py

Exits non-zero if any check fails. The checks are:

1. the Core 0.2 conformance suite
2. the Core 1.0 conformance suite
3. the Semantic Firewall self-check
4. validation of every document under ``examples/``
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _run(label: str, command: list[str]) -> bool:
    print()
    print("=" * 72)
    print(f"== {label}")
    print("=" * 72)
    result = subprocess.run(command, cwd=REPO_ROOT)
    return result.returncode == 0


def _examples_pass() -> bool:
    from sdl.document import load_schemas, validate_path

    schemas = load_schemas()
    ok = True
    documents = sorted((REPO_ROOT / "examples").rglob("*.sdl.yaml"))
    for document in documents:
        report = validate_path(document, schemas)
        relative = document.relative_to(REPO_ROOT)
        if report.status == "passed":
            print(f"PASS  {relative}")
        else:
            ok = False
            print(f"FAIL  {relative}")
            for diagnostic in sorted(report.diagnostics, key=lambda item: item.sort_key()):
                print(
                    f"      {diagnostic.severity} {diagnostic.phase} {diagnostic.code} "
                    f"{diagnostic.file}:{diagnostic.line}:{diagnostic.column} {diagnostic.message}"
                )
    return ok


def _examples_digest() -> dict[str, str]:
    """A digest of every example document."""
    import hashlib

    digest: dict[str, str] = {}
    for document in sorted((REPO_ROOT / "examples").rglob("*.sdl.yaml")):
        digest[document.relative_to(REPO_ROOT).as_posix()] = hashlib.sha256(
            document.read_bytes()
        ).hexdigest()
    return digest


def main() -> int:
    results: list[tuple[str, bool]] = []
    examples_before = _examples_digest()

    results.append(
        (
            "Core 0.2 conformance",
            _run(
                "Core 0.2 conformance suite",
                [sys.executable, "-m", "sdl", "validate", "--cases", "conformance/0.2/cases.yaml"],
            ),
        )
    )
    results.append(
        (
            "Core 1.0 conformance",
            _run(
                "Core 1.0 conformance suite",
                [sys.executable, "-m", "sdl", "validate", "--cases", "conformance/1.0/cases.yaml"],
            ),
        )
    )
    results.append(
        (
            "Semantic Firewall self-check",
            _run(
                "Semantic Firewall self-check",
                [sys.executable, "tests/test_verification.py"],
            ),
        )
    )
    results.append(
        (
            "Package structure",
            _run(
                "Package structure check",
                [sys.executable, "tests/test_package.py"],
            ),
        )
    )
    results.append(
        (
            "Pipeline integration",
            _run(
                "Pipeline integration test",
                [sys.executable, "tests/test_integration.py"],
            ),
        )
    )
    results.append(
        (
            "Code generation",
            _run(
                "Code generation test",
                [sys.executable, "tests/test_codegen.py"],
            ),
        )
    )
    results.append(
        (
            "SDL runtime",
            _run(
                "SDL runtime test",
                [sys.executable, "tests/test_runtime.py"],
            ),
        )
    )
    results.append(
        (
            "Assignability",
            _run(
                "Assignability test",
                [sys.executable, "tests/test_assignability.py"],
            ),
        )
    )
    results.append(
        (
            "Compatibility",
            _run(
                "Compatibility test",
                [sys.executable, "tests/test_compatibility.py"],
            ),
        )
    )
    results.append(
        (
            "Proposal recipes",
            _run(
                "Proposal recipes",
                [sys.executable, "tests/test_recipes.py"],
            ),
        )
    )

    print()
    print("=" * 72)
    print("== Example documents")
    print("=" * 72)
    results.append(("Example documents", _examples_pass()))

    print()
    print("=" * 72)
    print("== Summary")
    print("=" * 72)
    for label, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}")

    # The test suite must never change the repository.
    examples_after = _examples_digest()
    unchanged = examples_after == examples_before
    print(f"{'PASS' if unchanged else 'FAIL'}  Examples unchanged by the test suite")
    if not unchanged:
        for name in sorted(set(examples_before) | set(examples_after)):
            if examples_before.get(name) != examples_after.get(name):
                print(f"      changed: {name}")

    return 0 if all(ok for _, ok in results) and unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
