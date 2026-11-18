from pathlib import Path
from typing import Optional

from sdl.ir.graph import SymbolGraph
from .report import ValidationReport
from .reference_checker import ReferenceChecker
from .type_checker import TypeMismatchValidator
from .arch_checker import ArchitectureChecker
from .invariant_checker import InvariantChecker
from .compatibility import CompatibilityChecker


class SDLValidator:
    """
    The main orchestrator for SDL semantic validation.

    The order matters: the reference checker runs first, so that the other
    checkers work on a graph whose references resolve.
    """
    def __init__(self, graph: SymbolGraph, root: Optional[Path] = None):
        self.graph = graph
        self.root = root
        self.validators = [
            ReferenceChecker(graph),
            TypeMismatchValidator(graph),
            ArchitectureChecker(graph),
            InvariantChecker(graph),
            CompatibilityChecker(graph, root),
        ]

    def validate_all(self) -> ValidationReport:
        final_report = ValidationReport()
        for validator in self.validators:
            report = validator.validate()
            final_report.errors.extend(report.errors)
        return final_report
