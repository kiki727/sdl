from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Any
from .symbols import SymbolId

class EdgeId(str):
    """A unique identifier for an edge."""
    pass

class EdgeKind(Enum):
    CONTAINS = auto()      # Project -> Module / Module -> Symbol
    IMPLEMENTS = auto()    # Implementation -> Interface
    CALLS = auto()         # Method/FlowStep -> Method
    RETURNS = auto()       # Method -> Type
    HAS_PARAMETER = auto() # Method -> Type
    DEPENDS_ON = auto()    # Module -> Module
    HAS_STEP = auto()      # Flow -> FlowStep
    NEXT = auto()          # FlowStep -> FlowStep
    INPUT_BINDING = auto() # FlowStep -> Symbol (Input)
    OUTPUT_BINDING = auto()# FlowStep -> Symbol (Output)
    BINDS_TO = auto()      # Project -> Implementation (a binding of section 6.2)

@dataclass
class Edge:
    id: EdgeId
    kind: EdgeKind
    source: SymbolId
    target: SymbolId
    attributes: Dict[str, Any] = field(default_factory=dict)
