"""Layer 4: AST to Canonical IR.

The builder turns the AST into symbols and edges. Two properties matter:

* **Nothing is lost.** Every part of the document reaches the IR: the
  constraints and the policy of a project, the methods and the invariants of
  an interface, the outputs of a flow, the error handling of a step, the
  source location of an implementation.
* **The result is reproducible.** Identifiers are derived from the qualified
  name of a symbol, never from a counter or a random source, so the same
  document always produces the same graph.

The builder creates the structural relations: containment, declaration,
implementation, flow composition and flow sequence. The resolver creates the
reference relations: calls, returns, parameters and bindings.
"""

from __future__ import annotations

from typing import Any, Iterable

from sdl.ir.edges import Edge, EdgeKind
from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import (
    FlowStateVariable,
    FlowStepSymbol,
    FlowSymbol,
    ImplementationSymbol,
    InterfaceSymbol,
    MethodParameter,
    MethodSymbol,
    ModuleSymbol,
    ProjectSymbol,
    SymbolId,
    SymbolKind,
    TypeField,
    TypeKind,
    TypeSymbol,
)
from sdl.lowering.identity import edge_id, symbol_id
from sdl.types import expressions as sdl_types
from sdl.parser.ast import (
    ASTBinding,
    ASTClass,
    ASTFlow,
    ASTFlowStep,
    ASTImplementation,
    ASTInterface,
    ASTMethod,
    ASTModule,
    ASTProject,
    ASTType,
    ASTTypes,
)

_TYPE_KIND = {
    "compound": TypeKind.COMPOUND,
    "alias": TypeKind.ALIAS,
    "enum": TypeKind.ENUM,
}


class LoweringError(Exception):
    """A document that cannot be lowered into the canonical IR."""

    def __init__(self, message: str, file: str | None = None, line: int | None = None):
        super().__init__(message)
        self.message = message
        self.file = file
        self.line = line


class SymbolBuilder:
    """Builds the canonical IR from a list of AST nodes."""

    def __init__(self, graph: SymbolGraph):
        self.graph = graph
        self._edge_counts: dict[tuple[str, str, str], int] = {}

    # -- entry point ---------------------------------------------------------

    def lower(self, nodes: Iterable[Any]) -> None:
        """Lower a list of AST nodes into the graph."""
        materialised = list(nodes)
        self._add_builtins()
        for node in materialised:
            self._create_symbols(node)
        for node in materialised:
            self._create_edges(node)
        self._link_project()

    def _add_builtins(self) -> None:
        """Add the built-in types to the graph.

        The built-in types are part of the language, not of a project, so they
        are not contained by the project symbol. They exist as symbols so that
        a reference to ``Decimal`` resolves to something.
        """
        for name in sorted(sdl_types.SIMPLE_BUILTINS):
            self._add_builtin(name, TypeKind.SCALAR)
        for name in sorted(sdl_types.GENERIC_ARITY):
            self._add_builtin(name, TypeKind.GENERIC)

    def _add_builtin(self, name: str, type_kind: TypeKind) -> None:
        if self.graph.resolve_symbol(name) is not None:
            return
        self.graph.add_symbol(
            TypeSymbol(
                id=symbol_id("type", name),
                kind=SymbolKind.TYPE,
                name=name,
                qualified_name=name,
                type_kind=type_kind,
                metadata={"builtin": True},
            )
        )

    # -- identifiers ---------------------------------------------------------

    def _add_symbol(self, symbol: Any) -> SymbolId:
        existing = self.graph.resolve_symbol(symbol.qualified_name)
        if existing is not None:
            raise LoweringError(
                f"Duplicate qualified name {symbol.qualified_name!r}.",
                getattr(symbol, "file", None),
            )
        self.graph.add_symbol(symbol)
        return symbol.id

    def _add_edge(self, kind: EdgeKind, source: SymbolId, target: SymbolId) -> None:
        for edge in self.graph.edges.values():
            if edge.kind == kind and edge.source == source and edge.target == target:
                return
        key = (kind.name, str(source), str(target))
        index = self._edge_counts.get(key, 0)
        self._edge_counts[key] = index + 1
        self.graph.add_edge(
            Edge(
                id=edge_id(kind, source, target, index),
                kind=kind,
                source=source,
                target=target,
            )
        )

    # -- symbols -------------------------------------------------------------

    def _create_symbols(self, node: Any) -> None:
        if isinstance(node, ASTProject):
            self._project(node)
        elif isinstance(node, ASTTypes):
            for declaration in node.types:
                self._type(declaration, scope=None)
        elif isinstance(node, ASTModule):
            self._module(node)
        elif isinstance(node, ASTInterface):
            self._interface(node, scope=None)
        elif isinstance(node, ASTImplementation):
            self._implementation(node)
        elif isinstance(node, ASTFlow):
            self._flow(node)

    def _project(self, node: ASTProject) -> SymbolId:
        symbol = ProjectSymbol(
            id=symbol_id("proj", node.id),
            kind=SymbolKind.PROJECT,
            name=node.id,
            qualified_name=node.id,
            version=node.version,
            metadata={
                "constraints": self._constraints(node.constraints),
                "policy": self._policy(node.policy),
                "backend": self._backend(node.backend),
                "builds": self._builds(node.builds),
                "bindings": self._bindings(node.bindings),
                "imports": [item.path for item in node.imports],
            },
        )
        return self._add_symbol(symbol)

    @staticmethod
    def _module_imports(imports: Any) -> list[str]:
        """The modules a module document imports."""
        return [
            item.module
            for item in imports
            if getattr(item, "module", "")
        ]

    def _module(self, node: ASTModule) -> SymbolId:
        symbol = ModuleSymbol(
            id=symbol_id("mod", node.id),
            kind=SymbolKind.MODULE,
            name=node.id,
            qualified_name=node.id,
            metadata={
                "constraints": self._constraints(node.constraints),
                "imports": [item.path for item in node.imports],
                "module_imports": self._module_imports(node.imports),
                "package_imports": [
                    item.package for item in node.imports if getattr(item, "package", "")
                ],
            },
        )
        module_id = self._add_symbol(symbol)

        for declaration in node.types:
            self._type(declaration, scope=node.id)
        for declaration in node.interfaces:
            self._interface(declaration, scope=node.id)
        for declaration in node.classes:
            self._class(declaration, scope=node.id)
        for function in node.functions:
            self._method(function, scope=node.id, parent=None)
        return module_id

    def _type(self, node: ASTType, scope: str | None) -> SymbolId:
        qualified_name = f"{scope}::{node.id}" if scope else node.id
        symbol = TypeSymbol(
            id=symbol_id("type", qualified_name),
            kind=SymbolKind.TYPE,
            name=node.id,
            qualified_name=qualified_name,
            type_kind=_TYPE_KIND.get(node.kind, TypeKind.COMPOUND),
            fields=[
                TypeField(name=item.name, type_id=SymbolId(item.type_expr))
                for item in node.fields
            ],
            constraints=list(node.constraints),
            metadata={
                "enum_values": list(node.enum_values),
                "type_expression": node.type_expr,
                "scope": scope,
            },
        )
        return self._add_symbol(symbol)

    def _class(self, node: ASTClass, scope: str | None) -> SymbolId:
        qualified_name = f"{scope}::{node.id}" if scope else node.id
        symbol = TypeSymbol(
            id=symbol_id("class", qualified_name),
            kind=SymbolKind.TYPE,
            name=node.id,
            qualified_name=qualified_name,
            type_kind=TypeKind.COMPOUND,
            fields=[
                TypeField(name=name, type_id=SymbolId(type_expr))
                for name, type_expr in node.properties.items()
            ],
            metadata={"scope": scope},
        )
        return self._add_symbol(symbol)

    def _interface(self, node: ASTInterface, scope: str | None) -> SymbolId:
        qualified_name = f"{scope}::{node.id}" if scope else node.id
        symbol = InterfaceSymbol(
            id=symbol_id("int", qualified_name),
            kind=SymbolKind.INTERFACE,
            name=node.id,
            qualified_name=qualified_name,
            version=node.version,
            invariants=list(node.invariants),
            metadata={
                "invariants": list(node.invariants),
                "imports": [item.path for item in node.imports],
                "scope": scope,
                "method_ids": [],
            },
        )
        interface_id = self._add_symbol(symbol)

        method_ids: list[str] = []
        for method in node.methods:
            method_id = self._method(method, scope=scope, parent=node.id)
            method_ids.append(str(method_id))
        symbol.metadata["method_ids"] = method_ids
        return interface_id

    def _method(self, node: ASTMethod, scope: str | None, parent: str | None) -> SymbolId:
        parts = [part for part in (scope, parent, node.id) if part]
        qualified_name = "::".join(parts)
        symbol = MethodSymbol(
            id=symbol_id("meth", qualified_name),
            kind=SymbolKind.METHOD,
            name=node.id,
            qualified_name=qualified_name,
            parameters=[
                MethodParameter(name=name, type_id=SymbolId(type_expr))
                for name, type_expr in sorted(node.inputs.items())
            ],
            return_type_id=SymbolId(node.output) if node.output else None,
            metadata={
                "version": node.version,
                "invariants": list(node.invariants),
                "scope": scope,
                "owner": parent,
            },
        )
        return self._add_symbol(symbol)

    def _implementation(self, node: ASTImplementation) -> SymbolId:
        symbol = ImplementationSymbol(
            id=symbol_id("impl", node.id),
            kind=SymbolKind.IMPLEMENTATION,
            name=node.id,
            qualified_name=node.id,
            version=node.version,
            language=node.language,
            source_file=node.source_file,
            source_symbol=node.source_symbol,
            metadata={
                "implements_list": [item.interface for item in node.implements],
                "implements": [
                    {"interface": item.interface, "version": item.version}
                    for item in node.implements
                ],
                "source": {
                    "file": node.source_file,
                    "symbol": node.source_symbol,
                },
            },
        )
        return self._add_symbol(symbol)

    def _flow(self, node: ASTFlow) -> SymbolId:
        symbol = FlowSymbol(
            id=symbol_id("flow", node.id),
            kind=SymbolKind.FLOW,
            name=node.id,
            qualified_name=node.id,
            version=node.version,
            state_definitions={
                name: FlowStateVariable(name=name, type_id=SymbolId(type_expr))
                for name, type_expr in sorted(node.inputs.items())
            },
            metadata={
                "inputs": dict(node.inputs),
                "outputs": dict(node.outputs),
                "output_mapping": dict(node.output_mapping),
                "invariants": list(node.invariants),
                "imports": [item.path for item in node.imports],
                "step_order": [],
            },
        )
        flow_id = self._add_symbol(symbol)

        step_ids: list[str] = []
        for index, step in enumerate(node.steps):
            step_ids.append(str(self._step(step, node.id, index)))
        symbol.metadata["step_order"] = step_ids
        return flow_id

    def _step(self, node: ASTFlowStep, flow_id: str, index: int) -> SymbolId:
        qualified_name = f"{flow_id}::{node.id}"
        symbol = FlowStepSymbol(
            id=symbol_id("step", qualified_name),
            kind=SymbolKind.FLOW_STEP,
            name=node.id,
            qualified_name=qualified_name,
            metadata={
                "call_target": node.call,
                "mapping": dict(node.mapping),
                "output_map": dict(node.output_map),
                "condition": node.condition,
                "on_error": node.on_error,
                "retry": self._retry(node.retry),
                "order": index,
                "flow": flow_id,
            },
        )
        return self._add_symbol(symbol)

    # -- edges ---------------------------------------------------------------

    def _create_edges(self, node: Any) -> None:
        if isinstance(node, ASTProject):
            self._project_edges(node)
        elif isinstance(node, ASTModule):
            self._module_edges(node)
        elif isinstance(node, ASTInterface):
            self._interface_edges(node, scope=None)
        elif isinstance(node, ASTTypes):
            pass
        elif isinstance(node, ASTImplementation):
            pass
        elif isinstance(node, ASTFlow):
            self._flow_edges(node)

    def _link_project(self) -> None:
        """The project contains every project scoped symbol.

        A symbol is project scoped when its qualified name has no scope
        prefix. Methods, types and steps that belong to a module, an
        interface or a flow carry a scope and are contained by their owner.
        """
        project = self._find_project()
        if project is None:
            return
        for symbol in sorted(self.graph.symbols.values(), key=lambda item: item.qualified_name):
            if symbol.id == project:
                continue
            if symbol.metadata.get("builtin"):
                continue
            if "::" in symbol.qualified_name:
                continue
            self._add_edge(EdgeKind.CONTAINS, project, symbol.id)

    def _project_edges(self, node: ASTProject) -> None:
        project_id = self.graph.resolve_symbol(node.id)
        if project_id is None:
            return
        for declaration in node.interfaces:
            self._interface_edges(declaration, scope=None)
        for binding in node.bindings:
            self._binding_edges(binding, project_id)

    def _module_edges(self, node: ASTModule) -> None:
        module_id = self.graph.resolve_symbol(node.id)
        if module_id is None:
            return
        for declaration in node.types:
            self._contain(declaration.id, scope=node.id, source=module_id)
        for declaration in node.interfaces:
            self._interface_edges(declaration, scope=node.id, source=module_id)
            self._contain(declaration.id, scope=node.id, source=module_id)
        for function in node.functions:
            self._contain(function.id, scope=node.id, source=module_id)

    def _interface_edges(
        self,
        node: ASTInterface,
        scope: str | None,
        source: SymbolId | None = None,
    ) -> None:
        interface_id = self.graph.resolve_symbol(
            f"{scope}::{node.id}" if scope else node.id
        )
        if interface_id is None:
            return
        for method in node.methods:
            parts = [part for part in (scope, node.id, method.id) if part]
            method_id = self.graph.resolve_symbol("::".join(parts))
            if method_id is None:
                continue
            self._add_edge(EdgeKind.CONTAINS, interface_id, method_id)
            self._add_edge(EdgeKind.IMPLEMENTS, method_id, interface_id)

    def _flow_edges(self, node: ASTFlow) -> None:
        flow_id = self.graph.resolve_symbol(node.id)
        if flow_id is None:
            return
        previous: SymbolId | None = None
        for index, step in enumerate(node.steps):
            step_id = self.graph.resolve_symbol(f"{node.id}::{step.id}")
            if step_id is None:
                continue
            self._add_edge(EdgeKind.HAS_STEP, flow_id, step_id)
            if previous is not None:
                self._add_edge(EdgeKind.NEXT, previous, step_id)
            previous = step_id

    def _binding_edges(self, binding: ASTBinding, project_id: SymbolId) -> None:
        """A binding connects the project to an implementation."""
        implementation_id = self.graph.resolve_symbol(binding.implementation)
        if implementation_id is None:
            return
        self._add_edge(EdgeKind.BINDS_TO, project_id, implementation_id)

    # -- containment ---------------------------------------------------------

    def _contain(
        self,
        name: str,
        scope: str | None,
        source: SymbolId,
    ) -> None:
        qualified_name = f"{scope}::{name}" if scope else name
        target = self.graph.resolve_symbol(qualified_name)
        if target is None:
            return
        self._add_edge(EdgeKind.CONTAINS, source, target)

    def _find_project(self) -> SymbolId | None:
        for symbol in self.graph.symbols.values():
            if symbol.kind == SymbolKind.PROJECT:
                return symbol.id
        return None

    # -- fragments -----------------------------------------------------------

    @staticmethod
    def _constraints(constraints: Any) -> dict[str, Any]:
        if constraints is None:
            return {}
        return {
            "forbidden_imports": [
                {
                    "from": item.from_module,
                    "deny": list(item.deny),
                    "reason": item.reason,
                }
                for item in constraints.forbidden_imports
            ]
        }

    @staticmethod
    def _policy(policy: Any) -> dict[str, Any]:
        if policy is None:
            return {}
        return {
            "disallow_breaking_changes": policy.disallow_breaking_changes,
            "require_migration_for_type_change": policy.require_migration_for_type_change,
            "forbidden_id_changes": policy.forbidden_id_changes,
        }

    @staticmethod
    def _backend(backend: Any) -> dict[str, Any]:
        if backend is None:
            return {}
        return {
            "target": backend.target,
            "mode": backend.mode,
            "options": dict(backend.options),
        }

    @staticmethod
    def _builds(builds: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": build.id,
                "target": build.target,
                "mode": build.mode,
                "bindings_override": [
                    {
                        "interface": binding.interface,
                        "version": binding.version,
                        "implementation": binding.implementation,
                    }
                    for binding in build.bindings_override
                ],
            }
            for build in builds
        ]

    @staticmethod
    def _bindings(bindings: Any) -> list[dict[str, Any]]:
        return [
            {
                "interface": binding.interface,
                "version": binding.version,
                "implementation": binding.implementation,
            }
            for binding in bindings
        ]

    @staticmethod
    def _retry(retry: Any) -> dict[str, Any] | None:
        if retry is None:
            return None
        return {
            "attempts": retry.attempts,
            "backoff": retry.backoff,
            "initial_interval": retry.initial_interval,
            "max_interval": retry.max_interval,
        }
