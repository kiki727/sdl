"""The compiler: documents in, canonical IR out.

This is the orchestrator that the pipeline was missing. It runs the whole
chain::

    documents -> validate -> parse -> lower -> resolve -> firewall -> IR

The result is a :class:`CompileResult` that carries the canonical IR and a
single validation report covering every layer that ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sdl.diagnostics import ERROR, Report
from sdl.document import load_schemas, validate_path
from sdl.ir.graph import SymbolGraph
from sdl.lowering.resolver import SymbolResolver
from sdl.lowering.symbol_builder import SymbolBuilder
from sdl.parser.ast import ASTImport, ASTNode, ASTProject
from sdl.parser.yaml_parser import SDLYamlParser, SDLParserError
from sdl.validation.validator import SDLValidator


@dataclass
class CompileResult:
    """The outcome of a compilation."""

    graph: SymbolGraph | None = None
    report: Report = field(default_factory=Report)
    documents: list[str] = field(default_factory=list)
    root: Path | None = None

    @property
    def ok(self) -> bool:
        return self.graph is not None and self.report.status == "passed"

    @property
    def symbol_count(self) -> int:
        return len(self.graph.symbols) if self.graph else 0

    @property
    def edge_count(self) -> int:
        return len(self.graph.edges) if self.graph else 0


def _collect_imports(node: ASTNode) -> list[str]:
    imports = getattr(node, "imports", [])
    return [item.path for item in imports if isinstance(item, ASTImport)]


def _load_documents(
    entry: Path,
    report: Report,
) -> tuple[list[ASTNode], list[str]]:
    """Parse the entry document and everything it imports."""
    base = entry.resolve().parent
    parsed_nodes: list[ASTNode] = []
    visited: list[str] = []
    queue: list[Path] = [entry.resolve()]
    seen: set[Path] = set()

    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)

        try:
            content = current.read_text(encoding="utf-8")
        except OSError as error:
            report.add("parse", "error", "SDL-E302", f"Cannot read {current.name}: {error}", current.name)
            continue

        parser = SDLYamlParser(current.name)
        try:
            node = parser.parse(content)
        except SDLParserError as error:
            report.add(
                "parse",
                ERROR,
                "SDL-E100",
                error.message,
                current.name,
                error.line,
                error.column,
            )
            continue

        parsed_nodes.append(node)
        try:
            label = current.name if current == entry.resolve() else str(current.relative_to(base))
        except ValueError:
            label = current.name
        visited.append(label)

        if isinstance(node, ASTProject):
            for relative in _collect_imports(node):
                target = (base / relative).resolve()
                if target not in seen:
                    queue.append(target)

    return parsed_nodes, visited


def compile_project(
    entry: Path,
    schemas: dict[str, dict[str, Any]] | None = None,
    validate_documents: bool = True,
) -> CompileResult:
    """Compile an SDL project into the canonical IR."""
    entry = Path(entry)
    if entry.is_dir():
        candidates = sorted(entry.glob("*.sdl.yaml"))
        projects = [item for item in candidates if _is_project(item)]
        if not projects:
            report = Report()
            report.add(
                "parse",
                ERROR,
                "SDL-E302",
                f"No project document found in {entry.name}.",
                entry.name,
            )
            return CompileResult(report=report, root=entry)
        entry = projects[0]

    report = Report()
    schemas = schemas if schemas is not None else load_schemas()

    if validate_documents:
        document_report = validate_path(entry, schemas)
        for diagnostic in document_report.diagnostics:
            report.add(
                diagnostic.phase,
                diagnostic.severity,
                diagnostic.code,
                diagnostic.message,
                diagnostic.file,
                diagnostic.line,
                diagnostic.column,
                diagnostic.pointer,
            )
        if document_report.status == "failed":
            return CompileResult(report=report, root=entry)

    nodes, documents = _load_documents(entry, report)
    if not nodes:
        return CompileResult(report=report, documents=documents, root=entry)

    graph = SymbolGraph()
    builder = SymbolBuilder(graph)
    try:
        builder.lower(nodes)
    except Exception as error:  # noqa: BLE001 - lowering failures are diagnostics
        report.add("lowering", ERROR, "SDL-E511", str(error), entry.name)
        return CompileResult(report=report, documents=documents, root=entry)

    resolver = SymbolResolver(graph)
    for unresolved in resolver.resolve_all():
        report.add(
            "ir",
            ERROR,
            "SDL-E511",
            unresolved.message,
            _owner_name(graph, unresolved.source),
        )

    validator = SDLValidator(graph, entry.parent)
    firewall_report = validator.validate_all()
    for diagnostic in firewall_report.errors:
        report.add(
            "ir",
            diagnostic.severity,
            diagnostic.code,
            diagnostic.message,
            diagnostic.file,
            1,
            1,
            diagnostic.pointer,
        )

    return CompileResult(
        graph=graph,
        report=report,
        documents=documents,
        root=entry,
    )


def _is_project(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "kind: project" in content


def _owner_name(graph: SymbolGraph, symbol_id: Any) -> str:
    symbol = graph.get_symbol(symbol_id)
    return symbol.qualified_name if symbol else str(symbol_id)
