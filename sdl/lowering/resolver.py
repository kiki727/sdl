"""Layer 4, second half: reference resolution.

The resolver turns the string references of the parsed IR into edges between
symbols. It is the stage that decides whether a reference is real.

The resolver is **repeatable**. Running it again on a modified graph removes
the reference edges it owns and derives them from scratch. That is what makes
the firewall able to notice a proposal that broke a reference: the proposal
is applied, the graph is resolved again, and the dangling reference shows up
as an unresolved reference instead of being silently accepted.

The reference edges it owns are ``CALLS``, ``RETURNS``, ``HAS_PARAMETER``,
``IMPLEMENTS`` from an implementation to an interface, and ``DEPENDS_ON``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sdl.ir.edges import Edge, EdgeKind
from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import (
    FlowStateVariable,
    FlowStepSymbol,
    FlowSymbol,
    ImplementationSymbol,
    MethodSymbol,
    ModuleSymbol,
    SymbolId,
    TypeRef,
    TypeSymbol,
)
from sdl.lowering.identity import edge_id
from sdl.types import expressions as sdl_types

#: The edge kinds the resolver owns and may therefore rebuild.
OWNED_EDGE_KINDS = (
    EdgeKind.CALLS,
    EdgeKind.RETURNS,
    EdgeKind.HAS_PARAMETER,
    EdgeKind.DEPENDS_ON,
)

@dataclass
class UnresolvedReference:
    """A reference that could not be resolved to a symbol."""

    source: SymbolId
    kind: str
    reference: str
    message: str

    @property
    def target(self) -> None:
        return None


class SymbolResolver:
    """Resolves the string references of the IR into edges."""

    def __init__(self, graph: SymbolGraph):
        self.graph = graph
        self.unresolved: list[UnresolvedReference] = []

    # -- entry point ---------------------------------------------------------

    def _is_owned_edge(self, edge: Edge) -> bool:
        """Whether an edge belongs to the resolver and may be rebuilt.

        An ``IMPLEMENTS`` edge is owned only when it starts at an
        implementation. The edge that states that a method belongs to an
        interface is a structural relation and is left alone.
        """
        if edge.kind in OWNED_EDGE_KINDS:
            return True
        if edge.kind == EdgeKind.IMPLEMENTS:
            source = self.graph.get_symbol(edge.source)
            return isinstance(source, ImplementationSymbol)
        return False

    def resolve_all(self) -> list[UnresolvedReference]:
        """Resolve every reference. Returns the references that do not resolve."""
        self.unresolved = []
        self.graph.remove_edges(self._is_owned_edge)

        self._resolve_types()
        self._resolve_methods()
        self._resolve_implementations()
        self._resolve_flow_steps()
        self._resolve_flow_states()
        self._resolve_dependencies()
        return list(self.unresolved)

    # -- helpers -------------------------------------------------------------

    def _add_edge(self, kind: EdgeKind, source: SymbolId, target: SymbolId) -> None:
        existing = any(
            edge.kind == kind and edge.source == source and edge.target == target
            for edge in self.graph.edges.values()
        )
        if existing:
            return
        self.graph.add_edge(
            Edge(
                id=edge_id(kind, source, target),
                kind=kind,
                source=source,
                target=target,
            )
        )

    def _report(self, source: SymbolId, kind: str, reference: str, message: str) -> None:
        self.unresolved.append(
            UnresolvedReference(source=source, kind=kind, reference=reference, message=message)
        )

    def _resolve_name(self, name: str) -> SymbolId | None:
        """Resolve a type or symbol name in the project scope."""
        resolved = self.graph.resolve_symbol(name)
        if resolved is not None:
            return resolved
        if "::" in name:
            _, tail = name.split("::", 1)
            return self.graph.resolve_symbol(tail)
        return None

    def _resolve_type_expression(self, expression: str) -> tuple[SymbolId | None, list[SymbolId]]:
        """Resolve a type expression to its base type and its arguments."""
        reference, _ = self._type_reference(expression)
        if reference is None:
            return None, []
        if reference.kind == "union":
            members = [member.base for member in reference.arguments if member.base]
            return members[0] if members else None, members
        if reference.kind == "generic":
            arguments = [member.base for member in reference.arguments if member.base]
            return reference.base, arguments
        return reference.base, []

    def _type_reference(self, expression: str) -> tuple[TypeRef | None, list[SymbolId]]:
        """Resolve a type expression into the shape the IR keeps.

        The shape matters: the assignability rules of Core 0.2 section 6.7
        treat a union, an optional and a generic differently.
        """
        # An expression that is already the identifier of a symbol is resolved.
        # This happens when the graph was built by hand rather than lowered.
        if expression in self.graph.symbols:
            return TypeRef(kind="named", base=SymbolId(expression)), []

        try:
            parsed = sdl_types.parse(expression)
        except sdl_types.TypeSyntaxError:
            return None, []

        if isinstance(parsed, sdl_types.TypeName):
            base = self._resolve_name(parsed.name)
            if base is None:
                return None, []
            return TypeRef(kind="named", base=base), []

        if isinstance(parsed, sdl_types.TypeGeneric):
            base = self._resolve_name(parsed.name)
            if base is None:
                return None, []
            arguments: list[TypeRef] = []
            for argument in parsed.args:
                reference, _ = self._type_reference(str(argument))
                if reference is not None:
                    arguments.append(reference)
            return TypeRef(kind="generic", base=base, arguments=arguments), []

        if isinstance(parsed, sdl_types.TypeUnion):
            arguments = []
            for item in parsed.items:
                reference, _ = self._type_reference(str(item))
                if reference is not None:
                    arguments.append(reference)
            if not arguments:
                return None, []
            return TypeRef(kind="union", arguments=arguments), []

        return None, []

    # -- resolution ----------------------------------------------------------

    def _resolve_types(self) -> None:
        for symbol in self.graph.symbols.values():
            if not isinstance(symbol, TypeSymbol):
                continue
            for field in symbol.fields:
                resolved, arguments = self._resolve_type_expression(str(field.type_id))
                if resolved is None:
                    self._report(
                        symbol.id,
                        "type",
                        str(field.type_id),
                        f"Field {field.name!r} of type {symbol.name!r} refers to an unknown "
                        f"type {field.type_id!r}.",
                    )
                    continue
                field.type_id = resolved
                symbol.metadata.setdefault("field_types", {})[field.name] = resolved
                symbol.metadata.setdefault("field_type_arguments", {})[field.name] = list(arguments)
                reference, _ = self._type_reference(str(field.type_id))
                symbol.metadata.setdefault("field_type_refs", {})[field.name] = reference

            expression = symbol.metadata.get("type_expression")
            if isinstance(expression, str) and expression:
                resolved, arguments = self._resolve_type_expression(expression)
                if resolved is None:
                    self._report(
                        symbol.id,
                        "type",
                        expression,
                        f"Alias {symbol.name!r} refers to an unknown type {expression!r}.",
                    )
                else:
                    symbol.metadata["alias_target"] = resolved
                    reference, _ = self._type_reference(str(expression))
                    symbol.metadata["alias_type_ref"] = reference

    def _resolve_methods(self) -> None:
        for symbol in self.graph.symbols.values():
            if not isinstance(symbol, MethodSymbol):
                continue
            for parameter in symbol.parameters:
                # Keep the expression before it is overwritten by the resolved
                # identifier. ``_type_reference`` needs the original shape to
                # keep the arguments of a generic and the members of a union.
                expression = str(parameter.type_id)
                resolved, arguments = self._resolve_type_expression(expression)
                if resolved is None:
                    self._report(
                        symbol.id,
                        "parameter",
                        expression,
                        f"Parameter {parameter.name!r} of {symbol.qualified_name!r} refers to an "
                        f"unknown type {expression!r}.",
                    )
                    continue
                parameter.type_id = resolved
                parameter.type_arguments = arguments
                reference, _ = self._type_reference(expression)
                parameter.type_ref = reference
                self._add_edge(EdgeKind.HAS_PARAMETER, symbol.id, resolved)

            if symbol.return_type_id:
                expression = str(symbol.return_type_id)
                resolved, arguments = self._resolve_type_expression(expression)
                if resolved is None:
                    self._report(
                        symbol.id,
                        "return",
                        expression,
                        f"The return type of {symbol.qualified_name!r} refers to an unknown "
                        f"type {expression!r}.",
                    )
                else:
                    symbol.return_type_id = resolved
                    symbol.metadata["return_type_arguments"] = list(arguments)
                    reference, _ = self._type_reference(expression)
                    symbol.metadata["return_type_ref"] = reference
                    self._add_edge(EdgeKind.RETURNS, symbol.id, resolved)

    def _resolve_implementations(self) -> None:
        for symbol in self.graph.symbols.values():
            if not isinstance(symbol, ImplementationSymbol):
                continue
            for name in symbol.metadata.get("implements_list", []):
                interface_id = self._resolve_name(name)
                if interface_id is None:
                    self._report(
                        symbol.id,
                        "implements",
                        name,
                        f"Implementation {symbol.name!r} refers to an unknown interface {name!r}.",
                    )
                    continue
                self._add_edge(EdgeKind.IMPLEMENTS, symbol.id, interface_id)

    def _resolve_flow_steps(self) -> None:
        for symbol in self.graph.symbols.values():
            if not isinstance(symbol, FlowStepSymbol):
                continue
            target = symbol.metadata.get("call_target")
            if not isinstance(target, str) or not target:
                continue
            method_id = self.graph.resolve_symbol(target)
            if method_id is None and "::" in target:
                _, tail = target.split("::", 1)
                method_id = self.graph.resolve_symbol(tail)
            if method_id is None:
                self._report(
                    symbol.id,
                    "call",
                    target,
                    f"Flow step {symbol.name!r} calls {target!r}, which does not exist.",
                )
                continue
            self._add_edge(EdgeKind.CALLS, symbol.id, method_id)

    def _resolve_dependencies(self) -> None:
        """A module depends on the modules it imports."""
        for symbol in self.graph.symbols.values():
            if not isinstance(symbol, ModuleSymbol):
                continue
            for name in symbol.metadata.get("module_imports", []):
                target_id = self._resolve_name(name)
                if target_id is None:
                    self._report(
                        symbol.id,
                        "import",
                        name,
                        f"Module {symbol.name!r} imports {name!r}, which does not exist.",
                    )
                    continue
                self._add_edge(EdgeKind.DEPENDS_ON, symbol.id, target_id)

    # -- flow state ----------------------------------------------------------

    def _resolve_flow_states(self) -> None:
        """Resolve the Flow State of every flow.

        The Flow State is made of the declared inputs and of the variables the
        steps create through their ``output_map``. The type of a created
        variable is derived from what the called method returns: the whole
        result for ``result``, or the type of the field for ``result.field``.
        """
        for symbol in self.graph.symbols.values():
            if not isinstance(symbol, FlowSymbol):
                continue

            for variable in symbol.state_definitions.values():
                resolved, _ = self._resolve_type_expression(str(variable.type_id))
                if resolved is None:
                    self._report(
                        symbol.id,
                        "state",
                        str(variable.type_id),
                        f"Input {variable.name!r} of flow {symbol.name!r} refers to an "
                        f"unknown type {variable.type_id!r}.",
                    )
                    continue
                variable.type_id = resolved
                reference, _ = self._type_reference(str(variable.type_id))
                symbol.metadata.setdefault("state_type_refs", {})[variable.name] = reference

            for step_id in symbol.metadata.get("step_order", []):
                step = self.graph.get_symbol(step_id)
                if not isinstance(step, FlowStepSymbol):
                    continue
                return_type = self._return_type_of(step)
                for variable_name, output_path in step.metadata.get("output_map", {}).items():
                    type_id = self._output_type(return_type, output_path)
                    if type_id is None:
                        continue
                    reference = self._output_reference(step, return_type, output_path)
                    symbol.metadata.setdefault("state_type_refs", {})[variable_name] = reference
                    existing = symbol.state_definitions.get(variable_name)
                    if existing is None:
                        symbol.state_definitions[variable_name] = FlowStateVariable(
                            name=variable_name,
                            type_id=type_id,
                            origin_step=step.id,
                        )
                    else:
                        existing.type_id = type_id
                        existing.origin_step = step.id

    def _return_type_of(self, step: FlowStepSymbol) -> SymbolId | None:
        for edge in self.graph.get_edges_from(step.id):
            if edge.kind == EdgeKind.CALLS:
                method = self.graph.get_symbol(edge.target)
                if isinstance(method, MethodSymbol):
                    return method.return_type_id
        return None

    def _output_type(self, return_type: SymbolId | None, output_path: str) -> SymbolId | None:
        """The type of the value an output mapping places into the state."""
        if return_type is None:
            return None
        if "." not in output_path:
            return return_type
        _, _, field_path = output_path.partition(".")
        field_path = field_path.split(".")[0]
        type_symbol = self.graph.get_symbol(return_type)
        if isinstance(type_symbol, TypeSymbol):
            for field in type_symbol.fields:
                if field.name == field_path:
                    return field.type_id
        return return_type

    def _output_reference(
        self,
        step: FlowStepSymbol,
        return_type: SymbolId | None,
        output_path: str,
    ) -> TypeRef | None:
        """The shape of the value an output mapping places into the state.

        The identifier alone is not enough: the assignability rules of Core
        0.2 section 6.7 treat a union, an optional and a generic differently.
        """
        method = self._method_of(step)
        if method is None:
            return None
        reference = method.metadata.get("return_type_ref")
        if reference is None:
            return None
        if "." not in output_path:
            return reference

        _, _, field_path = output_path.partition(".")
        field_path = field_path.split(".")[0]
        type_symbol = self.graph.get_symbol(return_type)
        if not isinstance(type_symbol, TypeSymbol):
            return reference
        field_reference = (type_symbol.metadata.get("field_type_refs") or {}).get(field_path)
        return field_reference or reference

    def _method_of(self, step: FlowStepSymbol) -> MethodSymbol | None:
        for edge in self.graph.get_edges_from(step.id):
            if edge.kind == EdgeKind.CALLS:
                method = self.graph.get_symbol(edge.target)
                if isinstance(method, MethodSymbol):
                    return method
        return None
