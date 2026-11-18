"""The compatibility rules of specification section 5.

Section 5.2, the signature of a method:

* the names must be identical;
* the output of the implementation must be assignable to the output of the
  contract, which is **covariance**;
* the input of the contract must be assignable to the input of the
  implementation, which is **contravariance**.

Section 5.3, an implementation that declares an interface:

* every method of the interface must be implemented;
* every implemented method must be compatible with the one of the contract;
* the implementation may declare more methods, which are then not reachable
  through the interface.

Section 5.4, the version of an implementation must satisfy the version the
interface reference asks for, and a change that breaks a signature must
increment the major version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from sdl.backends.python_signature import PythonClass, read_class
from sdl.ir.edges import EdgeKind
from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import (
    ImplementationSymbol,
    InterfaceSymbol,
    MethodSymbol,
    SymbolId,
    TypeRef,
)
from sdl.types.assignability import TypeEnvironment
from sdl.types.semver import satisfies
from sdl.validation.report import Severity, ValidationError, ValidationReport

#: How a Python annotation maps to the name of a type of the specification.
PYTHON_TO_SDL = {
    "str": "String",
    "int": "Int",
    "float": "Float",
    "bool": "Boolean",
    "bytes": "Bytes",
    "None": "Unit",
    "Decimal": "Decimal",
    "UUID": "UUID",
    "date": "Date",
    "datetime": "DateTime",
}


class CompatibilityChecker:
    """Checks that the implementations satisfy the interfaces they declare."""

    def __init__(self, graph: SymbolGraph, root: Optional[Path] = None):
        self.graph = graph
        self.root = Path(root) if root else None
        self.environment = TypeEnvironment(graph)

    def validate(self) -> ValidationReport:
        """Check every implementation of the project."""
        report = ValidationReport()
        for symbol in self.graph.symbols.values():
            if not isinstance(symbol, ImplementationSymbol):
                continue
            for edge in self.graph.get_edges_from(symbol.id):
                if edge.kind != EdgeKind.IMPLEMENTS:
                    continue
                interface = self.graph.get_symbol(edge.target)
                if not isinstance(interface, InterfaceSymbol):
                    continue
                self._check_implementation(symbol, interface, report)
        return report

    # -- the implementation --------------------------------------------------

    def _check_implementation(
        self,
        implementation: ImplementationSymbol,
        interface: InterfaceSymbol,
        report: ValidationReport,
    ) -> None:
        version = self._required_version(implementation, interface)
        if version is not None and not satisfies(implementation.version, version):
            report.add_error(
                ValidationError(
                    code="SDL-E604",
                    severity=Severity.ERROR,
                    source=implementation.id,
                    target=interface.id,
                    message=(
                        f"The implementation {implementation.name!r} is at version "
                        f"{implementation.version!r}, which does not satisfy the version "
                        f"{version!r} the interface {interface.name!r} asks for."
                    ),
                )
            )

        realization = self._implementation_methods(implementation, interface, report)
        if realization is None:
            # The realization cannot be read. ``_implementation_methods``
            # reports SDL-E607 when the implementation declares Python code
            # that is missing or unreadable; there is nothing else to check.
            return
        methods = realization.methods

        contract = self._interface_methods(interface)

        for name, method in sorted(contract.items()):
            found = methods.get(name)
            if found is None:
                report.add_error(
                    ValidationError(
                        code="SDL-E604",
                        severity=Severity.ERROR,
                        source=implementation.id,
                        target=interface.id,
                        message=(
                            f"The implementation {implementation.name!r} does not "
                            f"implement {name!r}, which the interface "
                            f"{interface.name!r} declares."
                        ),
                    )
                )
                continue
            self._check_signature(implementation, interface, name, method, found, report)

    def _check_signature(
        self,
        implementation: ImplementationSymbol,
        interface: InterfaceSymbol,
        name: str,
        contract: MethodSymbol,
        found: Any,
        report: ValidationReport,
    ) -> None:
        """The signature of a method, as section 5.2 defines it."""
        expected = self._parameters_of(contract)
        actual = {
            parameter: annotation
            for parameter, annotation in found.parameters
            if parameter not in ("self", "cls")
        }

        for parameter, contract_type in expected.items():
            if parameter not in actual:
                # ``**kwargs`` accepts every keyword argument, so a parameter
                # the implementation does not name is still accepted.
                if getattr(found, "accepts_any_keyword", False):
                    continue
                report.add_error(
                    ValidationError(
                        code="SDL-E604",
                        severity=Severity.ERROR,
                        source=implementation.id,
                        target=interface.id,
                        message=(
                            f"The method {name!r} of the implementation "
                            f"{implementation.name!r} does not accept the parameter "
                            f"{parameter!r} the interface {interface.name!r} declares."
                        ),
                    )
                )
                continue

            contract_reference = contract_type
            if contract_reference is None:
                continue
            actual_reference = self._reference_of_annotation(actual[parameter])
            if actual_reference is None:
                self._unverifiable(
                    implementation,
                    interface,
                    report,
                    f"The parameter {parameter!r} of {name!r} has no type "
                    f"annotation the validator understands, so its signature "
                    f"cannot be verified against the interface {interface.name!r}.",
                )
                continue

            # Input contravariance: the contract's input must be acceptable
            # by the implementation.
            if not self.environment.assignable(contract_reference, actual_reference):
                report.add_error(
                    ValidationError(
                        code="SDL-E604",
                        severity=Severity.ERROR,
                        source=implementation.id,
                        target=interface.id,
                        message=(
                            f"The parameter {parameter!r} of {name!r} accepts "
                            f"{self._describe(actual_reference)}, which does not accept "
                            f"the {self._describe(contract_reference)} the interface "
                            f"{interface.name!r} declares."
                        ),
                    )
                )

        contract_return = contract.metadata.get("return_type_ref")
        if contract_return is None:
            return
        actual_return = self._reference_of_annotation(found.returns)
        if actual_return is None:
            self._unverifiable(
                implementation,
                interface,
                report,
                f"The return type of {name!r} has no annotation the validator "
                f"understands, so its signature cannot be verified against the "
                f"interface {interface.name!r}.",
            )
            return

        # Output covariance: the output of the implementation must be
        # assignable to the output of the contract.
        if not self.environment.assignable(actual_return, contract_return):
            report.add_error(
                ValidationError(
                    code="SDL-E604",
                    severity=Severity.ERROR,
                    source=implementation.id,
                    target=interface.id,
                    message=(
                        f"The method {name!r} of the implementation "
                        f"{implementation.name!r} returns "
                        f"{self._describe(actual_return)}, which is not assignable "
                        f"to the {self._describe(contract_return)} the interface "
                        f"{interface.name!r} declares."
                    ),
                )
            )

    # -- the pieces ----------------------------------------------------------

    def _interface_methods(self, interface: InterfaceSymbol) -> Dict[str, MethodSymbol]:
        methods: Dict[str, MethodSymbol] = {}
        for symbol in self.graph.symbols.values():
            if not isinstance(symbol, MethodSymbol):
                continue
            if symbol.metadata.get("owner") == interface.name:
                methods[symbol.name] = symbol
        return methods

    @staticmethod
    def _parameters_of(method: MethodSymbol) -> Dict[str, TypeRef]:
        parameters: Dict[str, TypeRef] = {}
        for parameter in method.parameters:
            reference = parameter.type_ref
            if reference is None:
                continue
            parameters[parameter.name] = reference
        return parameters

    def _implementation_methods(
        self,
        implementation: ImplementationSymbol,
        interface: InterfaceSymbol,
        report: ValidationReport,
    ) -> Optional[PythonClass]:
        """The methods of the realization of an implementation.

        The check is fail closed. When an implementation declares Python
        source, the source must exist and must be readable; otherwise the
        validator would claim that a contract holds without having looked at
        the code that is supposed to satisfy it.
        """
        if self.root is None:
            return None
        source = implementation.metadata.get("source") or {}
        file = source.get("file")
        symbol = source.get("symbol")
        if not isinstance(file, str) or not file:
            return None
        if not isinstance(symbol, str) or not symbol:
            return None

        # Only Python can be read here. A target in another language is out
        # of scope of this checker, not a reason to reject the project.
        language = (implementation.language or "").lower()
        if language not in ("python", "py"):
            return None

        path = (self.root / file).resolve()
        if not path.is_file():
            self._unverifiable(
                implementation,
                interface,
                report,
                f"The source file {file!r} of the implementation "
                f"{implementation.name!r} does not exist, so its signature "
                f"cannot be verified.",
            )
            return None

        realization = read_class(path, symbol)
        if realization is None:
            self._unverifiable(
                implementation,
                interface,
                report,
                f"The class {symbol!r} could not be read from {file!r}, so the "
                f"implementation {implementation.name!r} cannot be verified.",
            )
            return None
        return realization

    @staticmethod
    def _unverifiable(
        implementation: ImplementationSymbol,
        interface: InterfaceSymbol,
        report: ValidationReport,
        message: str,
    ) -> None:
        """Report a signature the validator could not read.

        Fail closed: an unreadable signature is an error, not a pass.
        """
        report.add_error(
            ValidationError(
                code="SDL-E607",
                severity=Severity.ERROR,
                source=implementation.id,
                target=interface.id,
                message=message,
            )
        )

    def _required_version(
        self,
        implementation: ImplementationSymbol,
        interface: InterfaceSymbol,
    ) -> Optional[str]:
        """The version the implementation reference asks for."""
        for entry in implementation.metadata.get("implements", []):
            if not isinstance(entry, dict):
                continue
            if entry.get("interface") != interface.name:
                continue
            version = entry.get("version")
            if isinstance(version, str):
                return version
        return None

    # -- the annotations -----------------------------------------------------

    def _reference_of_annotation(self, annotation: Optional[str]) -> Optional[TypeRef]:
        """The type of a Python annotation, in the terms of the specification."""
        if not annotation:
            return None
        text = annotation.strip()

        if "|" in text:
            members = []
            for part in text.split("|"):
                member = self._reference_of_annotation(part.strip())
                if member is None:
                    return None
                members.append(member)
            return TypeRef(kind="union", arguments=members)

        if text.endswith("]") and "[" in text:
            base, _, rest = text.partition("[")
            base = base.strip().rsplit(".", 1)[-1]
            arguments = []
            for part in _split_arguments(rest[:-1]):
                member = self._reference_of_annotation(part)
                if member is None:
                    return None
                arguments.append(member)
            base_reference = self._reference_of_annotation(base)
            if base_reference is None or base_reference.base is None:
                return None
            return TypeRef(
                kind="generic",
                base=base_reference.base,
                arguments=arguments,
            )

        name = text.rsplit(".", 1)[-1]
        name = PYTHON_TO_SDL.get(name, name)
        resolved = self.graph.resolve_symbol(name)
        if resolved is not None:
            return TypeRef(kind="named", base=resolved)

        for symbol in self.graph.symbols.values():
            if getattr(symbol, "name", None) == name:
                return TypeRef(kind="named", base=symbol.id)
        return None

    def _describe(self, reference: TypeRef) -> str:
        """The name of a type, for a diagnostic."""
        if reference.kind == "union":
            return " | ".join(self._describe(member) for member in reference.arguments)
        if reference.kind == "generic":
            base = self._name_of(reference.base)
            arguments = ", ".join(self._describe(member) for member in reference.arguments)
            return f"{base}[{arguments}]"
        return self._name_of(reference.base)

    def _name_of(self, type_id: Optional[SymbolId]) -> str:
        if type_id is None:
            return "Any"
        symbol = self.graph.get_symbol(type_id)
        return symbol.name if symbol is not None else str(type_id)


def _split_arguments(text: str) -> List[str]:
    """Split the arguments of a generic, on the commas that are not nested."""
    parts: List[str] = []
    depth = 0
    current = ""
    for character in text:
        if character in "[(":
            depth += 1
        elif character in "])":
            depth -= 1
        if character == "," and depth == 0:
            parts.append(current.strip())
            current = ""
            continue
        current += character
    if current.strip():
        parts.append(current.strip())
    return parts
