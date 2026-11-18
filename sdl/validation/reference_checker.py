from sdl.ir.graph import SymbolGraph
from .report import ValidationReport, ValidationError, Severity

class ReferenceChecker:
    """
    Validates that all references (especially CALLS edges) point to existing symbols.
    """
    def __init__(self, graph: SymbolGraph):
        self.graph = graph

    def validate(self) -> ValidationReport:
        report = ValidationReport()
        
        # Check all edges for broken references
        for edge_id, edge in self.graph.edges.items():
            # Every edge must have a valid source and target symbol
            # (Though graph.add_edge technically ensures they exist, 
            # we check this to be absolutely sure about the IR integrity)
            
            source_exists = self.graph.get_symbol(edge.source) is not None
            target_exists = self.graph.get_symbol(edge.target) is not None
            
            if not source_exists:
                report.add_error(ValidationError(
                    code="SDL-E511",
                    severity=Severity.ERROR,
                    source=edge.source,
                    target=edge.target,
                    message=f"Source symbol {edge.source} not found in registry"
                ))
            
            if not target_exists:
                report.add_error(ValidationError(
                    code="SDL-E511",
                    severity=Severity.ERROR,
                    source=edge.source,
                    target=edge.target,
                    message=f"Target symbol {edge.target} not found in registry"
                ))
                
        return report
