from sdl.ir.graph import SymbolGraph
from sdl.ir.edges import EdgeKind
from sdl.ir.symbols import ProjectSymbol
from .report import ValidationReport, ValidationError, Severity

class ArchitectureChecker:
    """
    Validates architectural constraints (e.g., forbidden imports).
    """
    def __init__(self, graph: SymbolGraph):
        self.graph = graph

    def validate(self) -> ValidationReport:
        report = ValidationReport()

        # 1. Find the project symbol to get constraints
        project = None
        for s in self.graph.symbols.values():
            if isinstance(s, ProjectSymbol):
                project = s
                break

        if not project:
            return report  # No project = no constraints

        constraints = project.metadata.get("constraints") or {}
        forbidden_imports = constraints.get("forbidden_imports", [])
        # format: [{"from": "ui", "deny": ["db", "infra"], "reason": "..."}]

        # 2. Check all DEPENDS_ON edges
        for edge_id, edge in self.graph.edges.items():
            if edge.kind == EdgeKind.DEPENDS_ON:
                source_id = edge.source
                target_id = edge.target

                source_sym = self.graph.get_symbol(source_id)
                target_sym = self.graph.get_symbol(target_id)

                if not source_sym or not target_sym:
                    continue

                # Check if this specific pair is forbidden
                for rule in forbidden_imports:
                    if source_sym.name == rule.get("from") and \
                       target_sym.name in rule.get("deny", []):

                        report.add_error(ValidationError(
                            code="SDL-E601",
                            severity=Severity.ERROR,
                            source=source_id,
                            target=target_id,
                            message=f"Forbidden import: {source_sym.name} -> {target_sym.name}. Reason: {rule.get('reason')}"
                        ))

        return report
