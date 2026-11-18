from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Dict, Any, List

class SymbolId(str):
    """A stable, unique identifier for a symbol. Not tied to the name."""
    pass

class SymbolKind(Enum):
    PROJECT = auto()
    MODULE = auto()
    INTERFACE = auto()
    METHOD = auto()
    TYPE = auto()
    IMPLEMENTATION = auto()
    FLOW = auto()
    FLOW_STEP = auto()

class TypeKind(Enum):
    SCALAR = auto()
    COMPOUND = auto()
    GENERIC = auto()
    OPTIONAL = auto()
    UNION = auto()
    REFERENCE = auto()
    ALIAS = auto()
    ENUM = auto()

@dataclass
class SourceSpan:
    """Represents the location of a symbol in the source YAML file."""
    file: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int

@dataclass
class Symbol:
    id: SymbolId
    kind: SymbolKind
    name: str
    qualified_name: str
    module_id: Optional[str] = None
    source_span: Optional[SourceSpan] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TypeRef:
    """A resolved type expression.

    The canonical IR keeps the identifier of the type an expression names,
    but a type expression may be more than a name: it may be a generic, a
    union, or an optional. The shape is kept here, so that the assignability
    rules of Core 0.2 section 6.7 can be applied.
    """

    kind: str = "named"  # "named", "generic", "union"
    base: Optional[SymbolId] = None
    arguments: List["TypeRef"] = field(default_factory=list)

    @property
    def is_union(self) -> bool:
        return self.kind == "union"

    @property
    def is_generic(self) -> bool:
        return self.kind == "generic"


@dataclass
class MethodParameter:
    name: str
    type_id: SymbolId
    optional: bool = False
    type_arguments: List[SymbolId] = field(default_factory=list)
    type_ref: Optional[TypeRef] = None

@dataclass
class FlowStateVariable:
    name: str
    type_id: SymbolId
    origin_step: Optional[SymbolId] = None # Which step created this variable

# Specialized Symbols
@dataclass
class ProjectSymbol(Symbol):
    version: str = ""

@dataclass
class ModuleSymbol(Symbol):
    pass

@dataclass
class InterfaceSymbol(Symbol):
    version: str = ""
    invariants: List[str] = field(default_factory=list)

@dataclass
class MethodSymbol(Symbol):
    parameters: List[MethodParameter] = field(default_factory=list)
    return_type_id: Optional[SymbolId] = None

@dataclass
class TypeField:
    name: str
    type_id: str # SymbolId
    optional: bool = False

@dataclass
class TypeSymbol(Symbol):
    type_kind: TypeKind = TypeKind.COMPOUND
    generic_parameters: List[str] = field(default_factory=list) # SymbolIds
    fields: List[TypeField] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)

@dataclass
class ImplementationSymbol(Symbol):
    version: str = ""
    language: str = ""
    source_file: Optional[str] = None
    source_symbol: Optional[str] = None

@dataclass
class FlowSymbol(Symbol):
    version: str = ""
    # Typed State: name -> variable definition
    state_definitions: Dict[str, FlowStateVariable] = field(default_factory=dict)

@dataclass
class FlowStepSymbol(Symbol):
    pass
