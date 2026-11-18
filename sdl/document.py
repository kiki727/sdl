"""The document level validator.

This module owns the validation of an SDL document against the rules of its
core version. It is the entry point that the compiler and the command line
share, so it lives above the layers rather than inside the command line.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sdl.diagnostics import Report
from sdl.schema.envelope import (
    CORE_VERSIONS,
    detect_version,
    validate_json_schema,
    validate_schema,
)
from sdl.semantics.core10 import Document as Document10
from sdl.semantics.core10 import analyze as analyze_core_1_0
from sdl.semantics.scope import Document, analyze as analyze_core_0_2
from sdl.yaml.subset import SubsetError, parse_file

PACKAGE_ROOT = Path(__file__).resolve().parent

SCHEMA_PATHS = {
    "0.2": PACKAGE_ROOT / "schema" / "sdl-0.2.schema.json",
    "1.0": PACKAGE_ROOT / "schema" / "sdl-1.0.schema.json",
}


def load_schemas() -> dict[str, dict[str, Any]]:
    """Load the JSON Schema of every supported core version."""
    schemas: dict[str, dict[str, Any]] = {}
    for version, path in SCHEMA_PATHS.items():
        with path.open("r", encoding="utf-8") as handle:
            schemas[version] = json.load(handle)
    return schemas


def document_id(kind: str | None, data: Any) -> str | None:
    """The identifier of a document, when it has one."""
    if kind not in ("project", "module", "interface", "flow", "implementation"):
        return None
    if not isinstance(data, dict):
        return None
    root = data.get(kind)
    if isinstance(root, dict) and isinstance(root.get("id"), str):
        return root["id"]
    return None


def validate_path(path: Path, schemas: dict[str, dict[str, Any]]) -> Report:
    """Validate a single SDL document.

    The version of the document is read from its envelope, and the document is
    validated against the rules of that version.
    """
    report = Report()
    file_label = path.name

    try:
        parsed = parse_file(path)
    except SubsetError as error:
        report.add("syntax", "error", error.code, error.message, file_label, error.line, error.column)
        return report
    except OSError:
        raise

    version = detect_version(parsed)
    schema = schemas.get(version or "")

    if schema is None:
        # The envelope does not name a supported core version. Report it and
        # stop; the shape of the document cannot be checked without a schema.
        validate_schema(parsed, file_label, report, version)
        return report

    kind = validate_schema(parsed, file_label, report, version)
    validate_json_schema(parsed, file_label, report, schema)

    identifier = document_id(kind, parsed.data)
    if version == "1.0":
        document = Document10(
            path=path.resolve(),
            rel=file_label,
            parsed=parsed,
            kind=kind,
            id=identifier,
        )
        analyze_core_1_0(document, report, schema)
    else:
        document = Document(
            path=path.resolve(),
            rel=file_label,
            parsed=parsed,
            kind=kind,
            id=identifier,
        )
        analyze_core_0_2(document, report, schema)

    return report


__all__ = [
    "CORE_VERSIONS",
    "SCHEMA_PATHS",
    "document_id",
    "load_schemas",
    "validate_path",
]
