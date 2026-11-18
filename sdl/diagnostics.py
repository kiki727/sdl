"""Shared diagnostics for the SDL toolchain.

This module is the single definition of the SDL diagnostic registry. Every
validation layer (YAML subset, envelope/schema, semantics, IR firewall) reports
through :class:`Report`, so a diagnostic has the same shape and the same code
regardless of which layer produced it.

A diagnostic always carries:

* ``phase``   - the pipeline layer that produced it
* ``severity`` - ``error``, ``warning`` or ``info``
* ``code``    - an ``SDL-Exxx`` / ``SDL-Wxxx`` code from the registry
* ``message`` - a human readable explanation
* ``location`` - file, JSON pointer, line and column

Diagnostics are deterministic: :meth:`Report.as_dict` sorts by
(file, line, column, code).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

ERROR = "error"
WARNING = "warning"
INFO = "info"


# ---------------------------------------------------------------------------
# Diagnostic registry
# ---------------------------------------------------------------------------

#: Core 0.2 codes (archive/specs/sdl-core-0.2.md section 7).
CODES_0_2: dict[str, str] = {
    "SDL-E100": "YAML parse error",
    "SDL-E101": "Duplicate mapping key",
    "SDL-E102": "Forbidden YAML feature",
    "SDL-E103": "Depth/size limit exceeded",
    "SDL-E200": "Invalid envelope",
    "SDL-E201": "Unknown kind",
    "SDL-E202": "Missing or multiple root keys",
    "SDL-E203": "Undefined field",
    "SDL-E204": "Missing mandatory field",
    "SDL-E205": "Invalid field type or value",
    "SDL-E210": "Invalid ID format",
    "SDL-E211": "Duplicate ID in scope",
    "SDL-E212": "Unknown reference",
    "SDL-E213": "Forbidden name shadowing",
    "SDL-E220": "Invalid semver version/range",
    "SDL-E300": "Import path outside root or invalid path",
    "SDL-E301": "Cyclic import",
    "SDL-E302": "Unknown module or file not found",
    "SDL-E303": "Duplicate import",
    "SDL-E400": "Invalid type expression",
    "SDL-E401": "Unknown type",
    "SDL-E402": "Cyclic alias",
    "SDL-E403": "Invalid assignability",
    "SDL-E404": "Unresolved type in code generation",
    "SDL-E405": "Forbidden use of Unit",
    "SDL-E406": "Invalid arity or generic argument",
    "SDL-E407": "Invalid inference object",
    "SDL-E408": "Invalid type declaration",
    "SDL-E410": "Unapproved inference in code generation",
    "SDL-W100": "Unapproved inference in validation",
    "SDL-W101": "Unresolved type in validation",
}

#: Core 1.0 additions (spec/sdl-core-1.0.md).
CODES_1_0: dict[str, str] = {
    "SDL-E501": "Type mismatch in flow mapping or condition",
    "SDL-E502": "Flow mapping references an undefined state variable",
    "SDL-E503": "Mandatory flow output is not populated",
    "SDL-E504": "Invalid condition expression",
    "SDL-E505": "Invalid retry policy",
    "SDL-E506": "Invalid error handling strategy",
    "SDL-E507": "Flow step does not exist",
    "SDL-E508": "Flow step does not belong to any flow",
    "SDL-E509": "Duplicate identifier in the canonical IR",
    "SDL-E510": "Flow has no entry point",
    "SDL-E511": "Broken reference in the canonical IR",
    "SDL-E512": "Type identifier does not resolve in the canonical IR",
    "SDL-E601": "Layering violation",
    "SDL-E602": "Proposal policy violation",
    "SDL-E603": "Binding does not resolve to a compatible implementation",
    "SDL-E604": "Implementation does not satisfy the interface contract",
    "SDL-E605": "The backend target is not implemented by the toolchain",
    "SDL-E606": "The backend target cannot host the language of an implementation",
    "SDL-E607": "Implementation signature cannot be verified",
    "SDL-E700": "Invalid proposal document",
    "SDL-E701": "Proposal patch target does not exist",
    "SDL-E702": "Proposal introduces a broken reference",
    "SDL-E703": "Stale proposal base version",
    "SDL-E704": "Conflicting proposal patches",
    "SDL-E705": "The merge of a proposal could not be written",
    "SDL-W200": "Flow has multiple entry points",
    "SDL-W201": "Implementation declares methods not present in the interface",
}

#: The complete registry.
DIAGNOSTIC_CODES: dict[str, str] = {**CODES_0_2, **CODES_1_0}

#: Codes that were reserved by 0.2 for a later core and are not emitted by
#: the document validation layers.
RESERVED_CODES: frozenset[str] = frozenset({"SDL-E404", "SDL-E410"})


def describe(code: str) -> str:
    """Return the registry description for a diagnostic code."""
    return DIAGNOSTIC_CODES.get(code, "Unregistered diagnostic")


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def json_pointer(parts: list[Any]) -> str:
    if not parts:
        return ""
    escaped = []
    for part in parts:
        text = str(part).replace("~", "~0").replace("/", "~1")
        escaped.append(text)
    return "/" + "/".join(escaped)


@dataclass
class Diagnostic:
    phase: str
    severity: str
    code: str
    message: str
    file: str
    line: int = 1
    column: int = 1
    pointer: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "location": {
                "file": self.file,
                "path": self.pointer,
                "line": self.line,
                "column": self.column,
            },
        }

    def sort_key(self) -> tuple[str, int, int, str]:
        return (self.file, self.line, self.column, self.code)


@dataclass
class Report:
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(
        self,
        phase: str,
        severity: str,
        code: str,
        message: str,
        file: str,
        line: int = 1,
        column: int = 1,
        pointer: str = "",
    ) -> None:
        diagnostic = Diagnostic(
            phase=phase,
            severity=severity,
            code=code,
            message=message,
            file=file,
            line=line,
            column=column,
            pointer=pointer,
        )
        identity = (diagnostic.code, diagnostic.file, diagnostic.pointer, diagnostic.line)
        for existing in self.diagnostics:
            if (existing.code, existing.file, existing.pointer, existing.line) == identity:
                return
        self.diagnostics.append(diagnostic)

    @property
    def errors(self) -> list[Diagnostic]:
        return [diagnostic for diagnostic in self.diagnostics if diagnostic.severity == ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [diagnostic for diagnostic in self.diagnostics if diagnostic.severity == WARNING]

    @property
    def status(self) -> str:
        return "failed" if self.errors else "passed"

    def as_dict(self) -> dict[str, Any]:
        ordered = sorted(self.diagnostics, key=lambda diagnostic: diagnostic.sort_key())
        return {
            "validation": {
                "status": self.status,
                "diagnostics": [diagnostic.as_dict() for diagnostic in ordered],
            }
        }

    def codes(self) -> set[str]:
        return {diagnostic.code for diagnostic in self.diagnostics}
