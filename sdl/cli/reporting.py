"""Rendering of validation reports."""

from __future__ import annotations

import json

import yaml

from sdl.diagnostics import Report


def as_json(report: Report) -> str:
    """The report as JSON."""
    return json.dumps(report.as_dict(), indent=2, ensure_ascii=False)


def as_yaml(report: Report) -> str:
    """The report as YAML."""
    return yaml.safe_dump(report.as_dict(), sort_keys=False, allow_unicode=True)


def format_report(report: Report, as_json_output: bool = False) -> str:
    """The report in the requested format."""
    return as_json(report) if as_json_output else as_yaml(report)


def print_diagnostics(report) -> None:
    """Print every diagnostic, sorted, one per line.

    It accepts a report or a plain list of diagnostics.
    """
    diagnostics = getattr(report, "diagnostics", report)
    for diagnostic in sorted(diagnostics, key=lambda item: item.sort_key()):
        print(
            f"{diagnostic.severity} {diagnostic.phase} {diagnostic.code} "
            f"{diagnostic.file}:{diagnostic.line}:{diagnostic.column} {diagnostic.message}"
        )
