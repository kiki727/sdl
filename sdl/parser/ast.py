"""The Abstract Syntax Tree of SDL Core 1.0.

Every node carries the location it was read from, so that a diagnostic can
point at the exact line and column of the offending element.

The AST is a faithful, lossless representation of a document. It performs no
validation: the schema and the semantic layers decide what is legal, and the
lowering layer decides what a symbol is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ASTNode:
    """The base class of every AST node. Carries the source location."""

    file: str | None = None
    line: int | None = None
    column: int | None = None


# ---------------------------------------------------------------------------
# Shared fragments
# ---------------------------------------------------------------------------


@dataclass
class ASTImport(ASTNode):
    """An import of another SDL document.

    A project, interface or flow document imports by relative ``path``. A
    module document imports other modules by ``module`` name, or an external
    package by ``package`` name.
    """

    path: str = ""
    module: str = ""
    package: str = ""


@dataclass
class ASTField(ASTNode):
    """A field of a compound type."""

    name: str = ""
    type_expr: str = ""


@dataclass
class ASTType(ASTNode):
    """A type declaration.

    ``kind`` is one of ``compound``, ``alias`` or ``enum``.
    """

    id: str = "unknown"
    version: str = "0.0.0"
    kind: str = "compound"
    fields: list[ASTField] = field(default_factory=list)
    type_expr: str | None = None
    enum_values: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass
class ASTMethod(ASTNode):
    """A method or function signature."""

    id: str = "unknown"
    version: str = "0.0.0"
    inputs: dict[str, str] = field(default_factory=dict)
    output: str | None = None
    invariants: list[str] = field(default_factory=list)


@dataclass
class ASTInterface(ASTNode):
    """A contract: a named set of methods and invariants."""

    id: str = "unknown"
    version: str = "0.0.0"
    imports: list[ASTImport] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    methods: list[ASTMethod] = field(default_factory=list)


@dataclass
class ASTClass(ASTNode):
    """A class declaration with typed properties."""

    id: str = "unknown"
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class ASTInterfaceRef(ASTNode):
    """A reference to an interface, optionally at a specific version."""

    interface: str = "unknown"
    version: str | None = None


@dataclass
class ASTImplementation(ASTNode):
    """A concrete realization of one or more interfaces."""

    id: str = "unknown"
    version: str = "0.0.0"
    implements: list[ASTInterfaceRef] = field(default_factory=list)
    language: str = ""
    source_file: str | None = None
    source_symbol: str | None = None


@dataclass
class ASTBinding(ASTNode):
    """A binding of an interface to an implementation."""

    interface: str = "unknown"
    version: str | None = None
    implementation: str = "unknown"


@dataclass
class ASTForbiddenImport(ASTNode):
    """An architectural prohibition."""

    from_module: str = "unknown"
    deny: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class ASTConstraints(ASTNode):
    """The architectural prohibitions of a project or module."""

    forbidden_imports: list[ASTForbiddenImport] = field(default_factory=list)


@dataclass
class ASTPolicy(ASTNode):
    """The procedural prohibitions of a project."""

    disallow_breaking_changes: bool = False
    require_migration_for_type_change: bool = False
    forbidden_id_changes: bool = False


@dataclass
class ASTBackend(ASTNode):
    """The backend configuration of a project."""

    target: str = "python"
    mode: str = "codegen"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ASTBuild(ASTNode):
    """A build profile, with optional binding overrides."""

    id: str = "unknown"
    target: str = "python"
    mode: str = "codegen"
    bindings_override: list[ASTBinding] = field(default_factory=list)


@dataclass
class ASTTypes(ASTNode):
    """A document that declares types and nothing else.

    The Core 1.0 shape of a types document is a mapping keyed by type id.
    The list form is also accepted, because a project document declares its
    types as a list.
    """

    id: str = "types"
    version: str = "0.0.0"
    types: list[ASTType] = field(default_factory=list)


@dataclass
class ASTModule(ASTNode):
    """A namespace grouping types, interfaces, classes and functions."""

    id: str = "unknown"
    version: str = "0.0.0"
    imports: list[ASTImport] = field(default_factory=list)
    types: list[ASTType] = field(default_factory=list)
    interfaces: list[ASTInterface] = field(default_factory=list)
    classes: list[ASTClass] = field(default_factory=list)
    functions: list[ASTMethod] = field(default_factory=list)
    constraints: ASTConstraints | None = None


@dataclass
class ASTProject(ASTNode):
    """The root of a system."""

    id: str = "unknown"
    version: str = "0.0.0"
    imports: list[ASTImport] = field(default_factory=list)
    types: list[ASTType] = field(default_factory=list)
    interfaces: list[ASTInterface] = field(default_factory=list)
    bindings: list[ASTBinding] = field(default_factory=list)
    backend: ASTBackend | None = None
    builds: list[ASTBuild] = field(default_factory=list)
    constraints: ASTConstraints | None = None
    policy: ASTPolicy | None = None


@dataclass
class ASTRetry(ASTNode):
    """The retry policy of a flow step."""

    attempts: int = 1
    backoff: str | None = None
    initial_interval: str | None = None
    max_interval: str | None = None


@dataclass
class ASTFlowStep(ASTNode):
    """One operation within a flow."""

    id: str = "unknown"
    call: str = ""
    mapping: dict[str, str] = field(default_factory=dict)
    output_map: dict[str, str] = field(default_factory=dict)
    condition: str | None = None
    on_error: str | None = None
    retry: ASTRetry | None = None


@dataclass
class ASTFlow(ASTNode):
    """A state machine for business logic orchestration."""

    id: str = "unknown"
    version: str = "0.0.0"
    imports: list[ASTImport] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    inputs: dict[str, str] = field(default_factory=dict)
    steps: list[ASTFlowStep] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    output_mapping: dict[str, str] = field(default_factory=dict)


@dataclass
class ASTPatch(ASTNode):
    """One patch of a proposal, as defined in specification section 8.3."""

    target: str = ""
    action: str = "replace"
    value: Any = None


@dataclass
class ASTProposal(ASTNode):
    """A formal request for change."""

    id: str = "unknown"
    target_version: str = "0.0.0"
    author: str = "unknown"
    rationale: str = ""
    patches: list[ASTPatch] = field(default_factory=list)
