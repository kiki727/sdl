"""The validation report of the Semantic Firewall.

The IR level firewall reports through the same diagnostic registry as the
document level layers, so every diagnostic in the toolchain carries an
``SDL-Exxx`` code, a phase, a severity and a location.

The API keeps the shape the proposal engine expects: ``is_valid()``,
``errors`` and ``add_error()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sdl.diagnostics import ERROR, INFO, WARNING, Diagnostic, Report


class Severity:
    """Severity levels, kept for compatibility with the original API."""

    INFO = INFO
    WARNING = WARNING
    ERROR = ERROR


@dataclass
class ValidationError:
    """A single IR level finding.

    ``code`` is an ``SDL-Exxx`` code from the diagnostic registry.
    """

    code: str
    severity: str
    source: Any
    target: Any
    message: str
    status: str = "FAILED"

    @property
    def rule_id(self) -> str:
        """The original name of this finding. Kept for compatibility."""
        return self.code


@dataclass
class ValidationReport:
    """The result of running the Semantic Firewall over a symbol graph."""

    errors: list[Diagnostic] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def is_valid(self) -> bool:
        return not any(diagnostic.severity == ERROR for diagnostic in self.errors)

    @property
    def warnings(self) -> list[Diagnostic]:
        return [diagnostic for diagnostic in self.errors if diagnostic.severity == WARNING]

    @property
    def errors_only(self) -> list[Diagnostic]:
        return [diagnostic for diagnostic in self.errors if diagnostic.severity == ERROR]

    def add_error(self, error: ValidationError) -> None:
        self.errors.append(
            Diagnostic(
                phase="ir",
                severity=error.severity,
                code=error.code,
                message=error.message,
                file=str(error.source),
                line=1,
                column=1,
                pointer=str(error.target) if error.target is not None else "",
            )
        )

    def codes(self) -> set[str]:
        return {diagnostic.code for diagnostic in self.errors}

    def as_dict(self) -> dict[str, Any]:
        return Report(diagnostics=list(self.errors)).as_dict()
