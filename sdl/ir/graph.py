from typing import Dict, List, Set, Optional
from .symbols import Symbol, SymbolId
from .edges import Edge, EdgeId

class SymbolGraph:
    """
    The Canonical IR representation of an SDL system as a Directed Graph.
    """
    def __init__(self):
        self.symbols: Dict[SymbolId, Symbol] = {}
        self.edges: Dict[EdgeId, Edge] = {}
        
        # Indices for fast lookup
        self._symbol_by_qualified_name: Dict[str, SymbolId] = {}
        self._edges_by_source: Dict[SymbolId, Set[EdgeId]] = {}
        self._edges_by_target: Dict[SymbolId, Set[EdgeId]] = {}

    def add_symbol(self, symbol: Symbol):
        self.symbols[symbol.id] = symbol
        self._symbol_by_qualified_name[symbol.qualified_name] = symbol.id
        return symbol.id

    def add_edge(self, edge: Edge):
        self.edges[edge.id] = edge
        
        if edge.source not in self._edges_by_source:
            self._edges_by_source[edge.source] = set()
        self._edges_by_source[edge.source].add(edge.id)
        
        if edge.target not in self._edges_by_target:
            self._edges_by_target[edge.target] = set()
        self._edges_by_target[edge.target].add(edge.id)

    def resolve_symbol(self, qualified_name: str) -> Optional[SymbolId]:
        return self._symbol_by_qualified_name.get(qualified_name)

    def get_symbol(self, symbol_id: SymbolId) -> Optional[Symbol]:
        return self.symbols.get(symbol_id)

    def get_edges_from(self, symbol_id: SymbolId) -> List[Edge]:
        edge_ids = self._edges_by_source.get(symbol_id, set())
        return [self.edges[ eid ] for eid in edge_ids]

    def get_edges_to(self, symbol_id: SymbolId) -> List[Edge]:
        edge_ids = self._edges_by_target.get(symbol_id, set())
        return [self.edges[ eid ] for eid in edge_ids]

    def find_symbol_by_kind(self, kind):
        return [s for s in self.symbols.values() if s.kind == kind]

    def remove_edges_of_kind(self, *kinds) -> None:
        """Remove every edge of the given kinds and rebuild the indices.

        The reference edges are owned by the resolver, which has to be able to
        re-derive them after a change. Removing them first keeps the graph
        free of duplicates.
        """
        self.remove_edges(lambda edge: edge.kind in kinds)

    def remove_edges(self, predicate) -> None:
        """Remove every edge the predicate accepts and rebuild the indices."""
        for edge_id in [
            edge_id for edge_id, edge in self.edges.items() if predicate(edge)
        ]:
            del self.edges[edge_id]
        self._reindex_edges()

    def _reindex_edges(self) -> None:
        self._edges_by_source = {}
        self._edges_by_target = {}
        for edge in self.edges.values():
            self._edges_by_source.setdefault(edge.source, set()).add(edge.id)
            self._edges_by_target.setdefault(edge.target, set()).add(edge.id)
