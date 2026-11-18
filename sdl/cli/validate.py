#!/usr/bin/env python3
"""SDL document validator.

Validates SDL documents against the specification of the core version declared
by their envelope. Core 0.2 and Core 1.0 are supported.

Usage:
    python -m sdl validate conformance/0.2/valid/project/sdl.yaml
    python -m sdl validate --json examples/payment_system/project.sdl.yaml
    python -m sdl validate --cases conformance/0.2/cases.yaml
    python -m sdl validate --cases conformance/1.0/cases.yaml

Exit codes (SDL Core 0.2 section 7.4):
    0 valid
    1 validation errors
    2 usage or I/O error
    3 internal validator error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from sdl.cli.reporting import format_report
from sdl.document import CORE_VERSIONS, load_schemas, validate_path


def run_cases(manifest_path: Path, schemas: dict[str, dict]) -> int:
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)

    cases = manifest.get("cases") if isinstance(manifest, dict) else None
    if not isinstance(cases, list):
        print(f"{manifest_path}: missing cases list", file=sys.stderr)
        return 2

    base = manifest_path.parent
    failures = 0
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("path"), str):
            print(f"FAIL  invalid manifest entry: {case!r}")
            failures += 1
            continue
        path = (base / case["path"]).resolve()
        expected_valid = bool(case.get("valid"))
        expected_code = case.get("code")
        expected_phase = case.get("phase")

        try:
            report = validate_path(path, schemas)
        except Exception as error:  # noqa: BLE001 - runner must report the case
            print(f"FAIL  {case['path']}: validator crashed: {error}")
            failures += 1
            continue

        if expected_valid:
            passed = report.status == "passed"
            detail = "" if passed else f" ({len(report.errors)} error(s))"
        else:
            matches = [
                diagnostic
                for diagnostic in report.diagnostics
                if diagnostic.code == expected_code
                and (expected_phase is None or diagnostic.phase == expected_phase)
            ]
            passed = bool(matches)
            detail = "" if passed else f" (expected {expected_phase}/{expected_code})"

        print(f"{'PASS' if passed else 'FAIL'}  {case['path']}{detail}")
        if not passed:
            failures += 1
            for diagnostic in sorted(report.diagnostics, key=lambda item: item.sort_key()):
                print(
                    f"      {diagnostic.severity} {diagnostic.phase} {diagnostic.code} "
                    f"{diagnostic.file}:{diagnostic.line}:{diagnostic.column} {diagnostic.message}"
                )

    total = len(cases)
    print(f"\n{total - failures}/{total} cases passed")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate SDL documents.")
    parser.add_argument("files", nargs="*", help="SDL .sdl.yaml files to validate")
    parser.add_argument("--json", action="store_true", help="emit the validation report as JSON")
    parser.add_argument("--cases", metavar="MANIFEST", help="run a conformance manifest")
    parser.add_argument(
        "--version",
        action="version",
        version=f"supported core versions: {', '.join(CORE_VERSIONS)}",
    )
    args = parser.parse_args(argv)

    try:
        schemas = load_schemas()
    except OSError as error:
        print(f"cannot read schema: {error}", file=sys.stderr)
        return 2

    if args.cases:
        return run_cases(Path(args.cases), schemas)

    if not args.files:
        parser.print_help(sys.stderr)
        return 2

    exit_code = 0
    for name in args.files:
        path = Path(name)
        try:
            report = validate_path(path, schemas)
        except OSError as error:
            print(f"{name}: {error}", file=sys.stderr)
            exit_code = max(exit_code, 2)
            continue
        except Exception as error:  # noqa: BLE001 - internal errors must use exit code 3
            print(f"{name}: internal validator error: {error}", file=sys.stderr)
            exit_code = max(exit_code, 3)
            continue

        print(format_report(report, args.json))
        if report.status == "failed":
            exit_code = max(exit_code, 1)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
