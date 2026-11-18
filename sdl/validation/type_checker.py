from typing import Optional
from sdl.ir.graph import SymbolGraph
from sdl.ir.edges import EdgeKind
from sdl.ir.symbols import (
    TypeSymbol, TypeKind, MethodSymbol, TypeRef,
    FlowStepSymbol, FlowSymbol
)
from .report import ValidationReport, ValidationError, Severity
from sdl.semantics.core10 import ConditionSyntaxError, parse_condition
from sdl.types import expressions as sdl_types
from sdl.types.assignability import TypeEnvironment


def _condition_paths(condition: str) -> list[str]:
    """The state paths a condition reads."""
    try:
        variables = parse_condition(condition)
    except ConditionSyntaxError:
        return []
    return [name for name, _, _ in variables]


class TypeMismatchValidator:
    """
    Strictly validates type compatibility between FlowStep mappings and Method parameters.
    """
    def __init__(self, graph: SymbolGraph):
        self.graph = graph
        self.environment = TypeEnvironment(graph)

    def validate(self) -> ValidationReport:
        report = ValidationReport()

        # Iterate through all CALLS edges
        for edge_id, edge in self.graph.edges.items():
            if edge.kind == EdgeKind.CALLS:
                source_id = edge.source
                target_id = edge.target

                source = self.graph.get_symbol(source_id)
                target = self.graph.get_symbol(target_id)

                if not source or not target:
                    continue

                if isinstance(source, FlowStepSymbol) and isinstance(target, MethodSymbol):
                    self._check_step_to_method_types(source, target, report)

        self._check_flow_state(report)
        self._check_flow_outputs(report)

        return report

    def _check_flow_state(self, report: ValidationReport):
        """Every state path a step reads must exist when the step runs.

        The Flow State of a step holds the inputs of the flow and the
        variables the earlier steps created. A step that reads a variable
        which does not exist yet has a broken data flow, whatever the types
        say.
        """
        for flow in self.graph.symbols.values():
            if not isinstance(flow, FlowSymbol):
                continue

            available = set(flow.state_definitions)
            for step_id in flow.metadata.get("step_order", []):
                step = self.graph.get_symbol(step_id)
                if not isinstance(step, FlowStepSymbol):
                    continue

                for parameter, path in (step.metadata.get("mapping") or {}).items():
                    self._check_state_path(flow, step, path, available, report, f"mapping {parameter!r}")

                condition = step.metadata.get("condition")
                if isinstance(condition, str) and condition:
                    for path in _condition_paths(condition):
                        self._check_state_path(flow, step, path, available, report, "condition")

                for variable in (step.metadata.get("output_map") or {}):
                    available.add(variable)

    def _check_state_path(
        self,
        flow: FlowSymbol,
        step: FlowStepSymbol,
        path: str,
        available: set[str],
        report: ValidationReport,
        context: str,
    ):
        root = path.split(".", 1)[0]
        if root in available:
            return
        report.add_error(ValidationError(
            code="SDL-E502",
            severity=Severity.ERROR,
            source=step.id,
            target=flow.id,
            message=f"Step {step.name!r} reads {root!r} through {context}, but that "
                    f"variable does not exist in the Flow State of flow {flow.name!r}."
        ))

    def _check_step_to_method_types(self, step: FlowStepSymbol, method: MethodSymbol, report: ValidationReport):
        # 1. Find the Flow containing terms
        flow_id = None
        for edge in self.graph.get_edges_to(step.id):
            if edge.kind == EdgeKind.HAS_STEP:
                flow_id = edge.source
                break
        
        if not flow_id:
            report.add_error(ValidationError(
                code="SDL-E508",
                severity=Severity.ERROR,
                source=step.id,
                target=None,
                message="FlowStep is not part of any Flow"
            ))
            return
            
        flow = self.graph.get_symbol(flow_id)
        
        # 2. Compare Method parameters vs Flow mapping
        provided_mapping = step.metadata.get("mapping", {})
        
        for param in method.parameters:
            param_name = param.name
            expected = param.type_ref
            if expected is None and param.type_id is not None:
                expected = TypeRef(kind="named", base=param.type_id)

            if param_name not in provided_mapping:
                if not param.optional:
                    report.add_error(ValidationError(
                        code="SDL-E501",
                        severity=Severity.ERROR,
                        source=step.id,
                        target=method.id,
                        message=f"Parameter '{param_name}' is required by method but missing in flow mapping"
                    ))
                continue

            state_path = provided_mapping[param_name]
            actual = self._resolve_state_reference(flow, state_path)

            if actual is None:
                report.add_error(ValidationError(
                    code="SDL-E501",
                    severity=Severity.ERROR,
                    source=step.id,
                    target=method.id,
                    message=f"Could not resolve type for state variable '{state_path}' in flow {flow.name}"
                ))
                continue

            if expected is None:
                continue

            # The data in the Flow State must be assignable to the type the
            # method declares (section 2.3.3), which is the rule of section
            # 6.7. An alias is transparent, and a union or an optional is not
            # the same identifier as its member, so comparing the identifiers
            # alone is not enough.
            if not self.environment.assignable(actual, expected):
                report.add_error(ValidationError(
                    code="SDL-E501",
                    severity=Severity.ERROR,
                    source=step.id,
                    target=method.id,
                    message=f"Type mismatch for parameter '{param_name}': Expected "
                            f"{self._describe(expected)}, received {self._describe(actual)}"
                ))

    def _resolve_state_reference(self, flow: FlowSymbol, state_path: str) -> Optional[TypeRef]:
        """The type of a state path, in the terms of the specification.

        The reference keeps the shape of the type — the arguments of a
        generic and the members of a union — which a bare identifier loses.
        It is what the assignability rules of section 6.7 need.
        """
        parts = state_path.split('.')
        base_var = parts[0]

        if base_var not in flow.state_definitions:
            return None

        variable = flow.state_definitions[base_var]

        references = flow.metadata.get("state_type_refs") or {}
        reference = references.get(base_var)
        if reference is None:
            reference = TypeRef(kind="named", base=variable.type_id)

        for part in parts[1:]:
            symbol = self.graph.get_symbol(reference.base)
            if not isinstance(symbol, TypeSymbol) or symbol.type_kind != TypeKind.COMPOUND:
                # The specification does not describe the shape of the value,
                # so the rest of the path cannot be resolved.
                return None
            field_reference = (symbol.metadata.get("field_type_refs") or {}).get(part)
            if field_reference is None:
                return None
            reference = field_reference

        return reference

    # -- the outputs of a flow ------------------------------------------------

    def _check_flow_outputs(self, report: ValidationReport) -> None:
        """The outputs of a flow must be populated by the state.

        Specification section 2.3.3: the data in the Flow State must be
        assignable to the type that is declared. The output mapping of a
        flow is the last mapping of the flow, so the rule applies to it as
        well: a flow may not promise a type that the state does not hold.
        """
        for flow in self.graph.symbols.values():
            if not isinstance(flow, FlowSymbol):
                continue

            if self._has_a_broken_step(flow):
                # The Flow State of a flow whose call does not resolve is
                # unknown, so its outputs cannot be checked. The broken call
                # is the diagnostic that matters.
                continue

            outputs = flow.metadata.get("outputs") or {}
            mapping = flow.metadata.get("output_mapping") or {}
            if not isinstance(outputs, dict) or not isinstance(mapping, dict):
                continue

            for name, expression in outputs.items():
                path = mapping.get(name)
                if not isinstance(path, str):
                    # A mandatory output that is not populated is reported by
                    # the document layer, with SDL-E503.
                    continue

                reference, problem = self._resolve_state_path(flow, path)
                if problem == "missing-variable":
                    report.add_error(ValidationError(
                        code="SDL-E502",
                        severity=Severity.ERROR,
                        source=flow.id,
                        target=flow.id,
                        message=f"The output {name!r} of flow {flow.name!r} reads "
                                f"{path.split('.', 1)[0]!r}, but that variable does not "
                                f"exist in the Flow State of the flow."
                    ))
                    continue
                if problem == "missing-field":
                    report.add_error(ValidationError(
                        code="SDL-E502",
                        severity=Severity.ERROR,
                        source=flow.id,
                        target=flow.id,
                        message=f"The output {name!r} of flow {flow.name!r} reads {path!r}, "
                                f"but that field does not exist in the type of the state."
                    ))
                    continue
                if problem == "opaque":
                    # The specification does not describe the shape of the
                    # value, so nothing can be said about the path.
                    continue

                declared = self._reference_of_expression(str(expression))
                if declared is None or reference is None:
                    continue

                if not self.environment.assignable(reference, declared):
                    report.add_error(ValidationError(
                        code="SDL-E501",
                        severity=Severity.ERROR,
                        source=flow.id,
                        target=flow.id,
                        message=f"The output {name!r} of flow {flow.name!r} is declared as "
                                f"{self._describe(declared)}, but the state holds "
                                f"{self._describe(reference)}."
                    ))

    def _has_a_broken_step(self, flow: FlowSymbol) -> bool:
        """Whether a step of a flow calls something that does not resolve."""
        for step_id in flow.metadata.get("step_order", []):
            step = self.graph.get_symbol(step_id)
            if not isinstance(step, FlowStepSymbol):
                continue
            if not step.metadata.get("call_target"):
                continue
            for edge in self.graph.get_edges_from(step.id):
                if edge.kind == EdgeKind.CALLS:
                    break
            else:
                return True
        return False

    def _resolve_state_path(self, flow: FlowSymbol, path: str) -> tuple[Optional[TypeRef], Optional[str]]:
        """The type of a state path, and the problem when it does not resolve.

        The problem is ``missing-variable`` when the root of the path is not
        part of the Flow State, ``missing-field`` when the root exists but
        the field does not, and ``opaque`` when the specification does not
        describe the shape of the value, so the path cannot be checked.
        """
        parts = path.split(".")
        variable = flow.state_definitions.get(parts[0])
        if variable is None:
            return None, "missing-variable"

        references = flow.metadata.get("state_type_refs") or {}
        reference = references.get(parts[0])
        if reference is None:
            reference = TypeRef(kind="named", base=variable.type_id)

        for part in parts[1:]:
            symbol = self.graph.get_symbol(reference.base)
            if not isinstance(symbol, TypeSymbol):
                return None, "opaque"
            if symbol.type_kind != TypeKind.COMPOUND:
                # The shape of the value is not described by the
                # specification, so the rest of the path cannot be checked.
                return None, "opaque"
            field_reference = (symbol.metadata.get("field_type_refs") or {}).get(part)
            if field_reference is None:
                return None, "missing-field"
            reference = field_reference

        return reference, None

    def _reference_of_expression(self, expression: str) -> Optional[TypeRef]:
        """The type of a type expression, in the terms of the specification."""
        try:
            parsed = sdl_types.parse(expression)
        except sdl_types.TypeSyntaxError:
            return None
        return self._reference_of_parsed(parsed)

    def _reference_of_parsed(self, parsed) -> Optional[TypeRef]:
        if isinstance(parsed, sdl_types.TypeName):
            base = self._resolve_name(parsed.name)
            return TypeRef(kind="named", base=base) if base is not None else None

        if isinstance(parsed, sdl_types.TypeGeneric):
            base = self._resolve_name(parsed.name)
            if base is None:
                return None
            arguments = []
            for argument in parsed.args:
                member = self._reference_of_parsed(argument)
                if member is None:
                    return None
                arguments.append(member)
            return TypeRef(kind="generic", base=base, arguments=arguments)

        if isinstance(parsed, sdl_types.TypeUnion):
            members = []
            for item in parsed.items:
                member = self._reference_of_parsed(item)
                if member is None:
                    return None
                members.append(member)
            return TypeRef(kind="union", arguments=members)

        return None

    def _resolve_name(self, name: str) -> Optional[str]:
        """The identifier of a type of the specification."""
        resolved = self.graph.resolve_symbol(name)
        if resolved is not None:
            return resolved
        for symbol in self.graph.symbols.values():
            if getattr(symbol, "name", None) == name:
                return symbol.id
        return None

    def _describe(self, reference: TypeRef) -> str:
        """The name of a type, for a diagnostic."""
        if reference.kind == "union":
            return " | ".join(self._describe(member) for member in reference.arguments)
        if reference.kind == "generic":
            base = self._name_of(reference.base)
            arguments = ", ".join(self._describe(member) for member in reference.arguments)
            return f"{base}<{arguments}>"
        return self._name_of(reference.base)

    def _name_of(self, type_id: Optional[str]) -> str:
        if type_id is None:
            return "Any"
        symbol = self.graph.get_symbol(type_id)
        return symbol.name if symbol is not None else str(type_id)
