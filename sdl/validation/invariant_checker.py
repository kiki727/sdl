from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import SymbolKind, FlowStepSymbol
from sdl.ir.edges import EdgeKind
from .report import ValidationReport, ValidationError, Severity

class InvariantChecker:
    """
    Validates global invariants of the SDL Symbol Graph.
    """
    def __init__(self, graph: SymbolGraph):
        self.graph = graph

    def validate(self) -> ValidationReport:
        report = ValidationReport()
        self._check_unique_symbol_ids(report)
        self._check_flow_reachability(report)
        return report

    def _check_unique_symbol_ids(self, report: ValidationReport):
        names_seen = {}
        for sid, sym in self.graph.symbols.items():
            if sym.qualified_name in names_seen:
                report.add_error(ValidationError(
                    code="SDL-E509",
                    severity=Severity.ERROR,
                    source=sid,
                    target=names_seen[sym.qualified_name],
                    message=f"Duplicate qualified name: {sym.qualified_name}"
                ))
            names_seen[sym.qualified_name] = sid

    def _check_flow_reachability(self, report: ValidationReport):
        flows = [s for s in self.graph.symbols.values() if s.kind == SymbolKind.FLOW]
        for flow in flows:
            steps = [s for s in self.graph.symbols.values() 
                     if isinstance(s, FlowStepSymbol) and 
                        any(e.kind == EdgeKind.HAS_STEP and e.source == flow.id for e in self.graph.get_edges_to(s.id))]
            if not steps: continue
            
            incoming_next = {s.id: 0 for s in steps}
            for step in steps:
                for e in self.graph.get_edges_from(step.id):
                    if e.kind == EdgeKind.NEXT and e.target in [st.id for st in steps]:
                        incoming_next[e.target] += 1
            
            entries = [sid for sid, count in incoming_next.items() if count == 0]
            if not entries:
                report.add_error(ValidationError(
                    code="SDL-E510",
                    severity=Severity.ERROR,
                    source=flow.id,
                    target=None,
                    message=f"Flow {flow.name} has no entry step (cyclic)."
                ))
            elif len(entries) > 1:
                report.add_error(ValidationError(
                    code="SDL-W200",
                    severity=Severity.WARNING,
                    source=flow.id,
                    target=None,
                    message=f"Flow {flow.name} has multiple entries: {entries}"
                ))
