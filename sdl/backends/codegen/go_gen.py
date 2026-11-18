"""The Go back end.

Specification section 7.1: the generator creates complete source files in the
target language. The output is deterministic: the same canonical IR always
produces the same files, byte for byte.

The generated application has four parts:

* the **types**, the compound types of the specification, as Go structs;
* the **interfaces**, the contracts of the specification, as Go interfaces;
* the **flows**, the business logic, as functions with an explicit data flow;
* the **runtime**, the small amount of machinery the flows need: a registry
  that resolves a name to an implementation, and a dispatcher that calls it.

A flow never imports a concrete implementation. It names the interface or the
function of the specification, and the registry resolves the name through the
bindings of the project. That is what makes the implementation replaceable
without touching the business logic.

Two things are specific to the language. Go has no keyword arguments and no
dynamic typing, so the inputs of a method travel as a single ``map[string]any``,
the way the runtime calls it, and the dispatcher reaches the method of an
implementation by reflection, the way JavaScript reaches a property. And the
Flow State is a ``map[string]any``, so a path into it is read with the runtime
helper ``Field`` rather than with a field selector.

Nothing the document wrote is ever copied into the generated source as raw
text. A condition is parsed and rendered, a type is mapped to a Go type, and a
name is rendered as a string literal.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

from sdl.flow.expressions import ConditionSyntaxError, parse_condition, render_go
from sdl.ir.edges import EdgeKind
from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import (
    FlowStepSymbol,
    FlowSymbol,
    ImplementationSymbol,
    InterfaceSymbol,
    MethodSymbol,
    ProjectSymbol,
    TypeKind,
    TypeRef,
    TypeSymbol,
)

HEADER = "// Do not edit: this file is generated from the SDL specification.\n\n"

#: How a built-in type is written in Go.
SCALARS: Dict[str, str] = {
    "String": "string",
    "Int": "int",
    "Float": "float64",
    "Decimal": "float64",
    "Boolean": "bool",
    "UUID": "string",
    "Date": "string",
    "DateTime": "string",
    "Bytes": "[]byte",
    "Unit": "struct{}",
}

#: The built-in types that take type arguments.
GENERIC_BUILTINS = ("List", "Map", "Optional", "Result")

#: The keywords of Go, and the locals the generated source already uses.
GO_KEYWORDS = frozenset(
    {
        "break", "case", "chan", "const", "continue", "default", "defer",
        "else", "fallthrough", "for", "func", "go", "goto", "if", "import",
        "interface", "map", "package", "range", "return", "select", "struct",
        "switch", "type", "var",
    }
)
RESERVED_LOCALS = frozenset({"registry", "state", "_result", "_step", "err", "_"})


def snake(name: str) -> str:
    """``PaymentRequest`` becomes ``payment_request``."""
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return text.replace("-", "_").replace(".", "_").lower()


def pascal(name: str) -> str:
    """``get_hero_content`` becomes ``GetHeroContent``."""
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", str(name)) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts)


def go_local(name: str) -> str:
    """A name that can be a local of the generated Go."""
    text = str(name)
    if text in GO_KEYWORDS or text in RESERVED_LOCALS or not text:
        return text + "_"
    return text


def _string(value: Any) -> str:
    """A value as a Go string literal, escaped by the JSON writer."""
    return json.dumps(str(value), ensure_ascii=False)


def _seconds(value: Any) -> float:
    """A duration of the specification, in seconds."""
    if not isinstance(value, str):
        return 1.0
    digits = value.rstrip("ms")
    try:
        number = float(digits)
    except ValueError:
        return 1.0
    if value.endswith("ms"):
        return number / 1000.0
    if value.endswith("m"):
        return number * 60.0
    return number


def _float(value: Any) -> str:
    """A duration of the specification as a Go float literal."""
    return repr(_seconds(value))


class GoCodegen:
    """Generates a Go application from the canonical IR."""

    def __init__(self, graph: SymbolGraph):
        self.graph = graph

    # -- entry point ---------------------------------------------------------

    def generate(self) -> Dict[str, str]:
        """The generated files, keyed by their path relative to the output root."""
        files: Dict[str, str] = {}

        files["runtime/registry.go"] = self._registry_module()
        files["runtime/errors.go"] = self._errors_module()
        files["runtime/dispatch.go"] = self._dispatch_module()
        files["runtime/values.go"] = self._values_module()
        files["runtime/result.go"] = self._result_module()

        for symbol in self._declared_types():
            files[f"types/{snake(symbol.name)}.go"] = self._type_module(symbol)

        for symbol in self._symbols(InterfaceSymbol):
            files[f"interfaces/{snake(symbol.name)}.go"] = self._interface_module(symbol)

        for symbol in self._symbols(ImplementationSymbol):
            files[f"implementations/{snake(symbol.name)}.go"] = self._implementation_module(symbol)

        for module in self._modules():
            files[f"implementations/{snake(module)}.go"] = self._module_module(module)

        for symbol in self._symbols(FlowSymbol):
            files[f"flows/{snake(symbol.name)}.go"] = self._flow_module(symbol)

        files["main.go"] = self._main_module()
        files["go.mod"] = self._go_mod()
        files["README.md"] = self._readme()
        return files

    # -- graph access --------------------------------------------------------

    def _module_path(self) -> str:
        project = self._project()
        return snake(project.name) if project else "application"

    def _symbols(self, kind) -> List[Any]:
        return [
            symbol
            for symbol in sorted(self.graph.symbols.values(), key=lambda item: item.qualified_name)
            if isinstance(symbol, kind)
        ]

    def _module_functions(self) -> List[MethodSymbol]:
        """The functions a module of the specification declares."""
        functions = [
            symbol
            for symbol in self.graph.symbols.values()
            if isinstance(symbol, MethodSymbol)
            and not symbol.metadata.get("owner")
            and symbol.metadata.get("scope")
        ]
        return sorted(functions, key=lambda item: item.qualified_name)

    def _modules(self) -> List[str]:
        return sorted({str(symbol.metadata["scope"]) for symbol in self._module_functions()})

    def _declared_types(self) -> List[TypeSymbol]:
        return [
            symbol
            for symbol in self._symbols(TypeSymbol)
            if not symbol.metadata.get("builtin")
        ]

    def _project(self) -> Optional[ProjectSymbol]:
        for symbol in self.graph.symbols.values():
            if isinstance(symbol, ProjectSymbol):
                return symbol
        return None

    def _methods_of(self, interface: InterfaceSymbol) -> List[MethodSymbol]:
        methods = [
            symbol
            for symbol in self.graph.symbols.values()
            if isinstance(symbol, MethodSymbol)
            and symbol.metadata.get("owner") == interface.name
        ]
        return sorted(methods, key=lambda item: item.name)

    def _class_name(self, symbol: ImplementationSymbol) -> str:
        source = symbol.metadata.get("source") or {}
        name = source.get("symbol")
        if isinstance(name, str) and name:
            return pascal(name)
        return pascal(symbol.name)

    def _bindings(self) -> List[tuple[str, str]]:
        project = self._project()
        if project is None:
            return []
        bindings = project.metadata.get("bindings", [])
        result = []
        for binding in bindings:
            interface = binding.get("interface")
            implementation = binding.get("implementation")
            if isinstance(interface, str) and isinstance(implementation, str):
                result.append((interface, implementation))
        return result

    # -- typing --------------------------------------------------------------

    def _render_type(
        self,
        reference: Optional[TypeRef],
        imports: Set[str],
        type_id: Any = None,
        arguments: Optional[List[Any]] = None,
        prefix: str = "",
    ) -> str:
        """The Go type of a resolved reference.

        The reference carries the shape of a generic or a union, so a nested
        ``List<Optional<String>>`` keeps its arguments. When there is no
        reference, the flat identifier and its arguments are used.
        """
        if reference is not None:
            return self._render_reference(reference, imports, prefix)
        return self._render_flat(type_id, imports, arguments or [], prefix)

    def _render_reference(self, reference: TypeRef, imports: Set[str], prefix: str) -> str:
        if reference.kind == "union":
            return "any"
        symbol = self.graph.get_symbol(reference.base) if reference.base else None
        if symbol is None or not isinstance(symbol, TypeSymbol):
            return "any"
        if symbol.metadata.get("builtin"):
            if symbol.name in GENERIC_BUILTINS and reference.arguments:
                rendered = [
                    self._render_reference(item, imports, prefix)
                    for item in reference.arguments
                ]
                return self._generic(symbol.name, rendered, imports)
            return SCALARS.get(symbol.name, "any")
        name = self._named(symbol, imports, prefix)
        if reference.arguments:
            rendered = [
                self._render_reference(item, imports, prefix)
                for item in reference.arguments
            ]
            return f"{name}[{', '.join(rendered)}]"
        return name

    def _render_flat(
        self,
        type_id: Any,
        imports: Set[str],
        arguments: List[Any],
        prefix: str,
    ) -> str:
        if type_id is None:
            return "any"
        symbol = self.graph.get_symbol(type_id)
        if symbol is None or not isinstance(symbol, TypeSymbol):
            return "any"
        if symbol.metadata.get("builtin"):
            if symbol.name in GENERIC_BUILTINS and arguments:
                rendered = [self._render_flat(item, imports, [], prefix) for item in arguments]
                return self._generic(symbol.name, rendered, imports)
            return SCALARS.get(symbol.name, "any")
        return self._named(symbol, imports, prefix)

    def _named(self, symbol: TypeSymbol, imports: Set[str], prefix: str) -> str:
        if symbol.metadata.get("builtin"):
            return SCALARS.get(symbol.name, "any")
        if prefix:
            imports.add(f'"{self._module_path()}/types"')
            return prefix + symbol.name
        return symbol.name

    def _generic(self, name: str, arguments: List[str], imports: Set[str]) -> str:
        if name == "Optional":
            inner = arguments[0] if arguments else "any"
            return f"*{inner}"
        if name == "List":
            inner = arguments[0] if arguments else "any"
            return f"[]{inner}"
        if name == "Map":
            key = arguments[0] if arguments else "string"
            value = arguments[1] if len(arguments) > 1 else "any"
            return f"map[{key}]{value}"
        if name == "Result":
            imports.add(f'"{self._module_path()}/runtime"')
            inner = ", ".join(arguments) if arguments else "any, any"
            return f"runtime.Result[{inner}]"
        return name

    def _import_block(self, imports: Set[str]) -> str:
        statements = sorted(set(imports))
        if not statements:
            return ""
        stdlib = [statement for statement in statements if "/" not in statement]
        module = [statement for statement in statements if "/" in statement]
        lines = ["import ("]
        for statement in stdlib:
            lines.append(f"\t{statement}")
        if stdlib and module:
            lines.append("")
        for statement in module:
            lines.append(f"\t{statement}")
        lines.append(")")
        return "\n".join(lines) + "\n\n"

    # -- types ---------------------------------------------------------------

    def _type_module(self, symbol: TypeSymbol) -> str:
        imports: Set[str] = set()
        if symbol.type_kind == TypeKind.ENUM:
            body = self._enum_body(symbol)
        elif symbol.type_kind == TypeKind.ALIAS:
            body = self._alias_body(symbol, imports)
        else:
            body = self._struct_body(symbol, imports)
        return HEADER + "package types\n\n" + self._import_block(imports) + body

    def _struct_body(self, symbol: TypeSymbol, imports: Set[str]) -> str:
        generic = ""
        if symbol.generic_parameters:
            generic = "[" + ", ".join(f"{name} any" for name in symbol.generic_parameters) + "]"
        lines = [f"// {symbol.name} is the SDL type {symbol.name}."]
        lines.append(f"type {symbol.name}{generic} struct {{")
        arguments_of = symbol.metadata.get("field_type_arguments", {})
        references = symbol.metadata.get("field_type_refs", {})
        for field in symbol.fields:
            rendered = self._render_type(
                references.get(field.name),
                imports,
                field.type_id,
                arguments_of.get(field.name),
            )
            lines.append(f"\t{pascal(field.name)} {rendered}")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def _alias_body(self, symbol: TypeSymbol, imports: Set[str]) -> str:
        target = symbol.metadata.get("alias_target")
        if target:
            rendered = self._render_type(symbol.metadata.get("alias_type_ref"), imports, target)
        else:
            rendered = "any"
        return f"// {symbol.name} is the SDL alias {symbol.name}.\ntype {symbol.name} = {rendered}\n"

    def _enum_body(self, symbol: TypeSymbol) -> str:
        values = [str(value) for value in symbol.metadata.get("enum_values", [])]
        lines = [f"// {symbol.name} is the SDL enum {symbol.name}."]
        lines.append(f"type {symbol.name} string")
        if values:
            lines.append("")
            lines.append("const (")
            for value in values:
                lines.append(
                    f"\t{self._enum_constant(symbol.name, value)} {symbol.name} = "
                    f"{json.dumps(value, ensure_ascii=False)}"
                )
            lines.append(")")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _enum_constant(type_name: str, value: str) -> str:
        suffix = pascal(value)
        if not suffix or suffix[0].isdigit():
            suffix = "Value" + suffix
        return type_name + suffix

    # -- interfaces ----------------------------------------------------------

    def _interface_module(self, symbol: InterfaceSymbol) -> str:
        lines = [f"// {symbol.name} is the SDL interface {symbol.name}."]
        lines.append(f"type {symbol.name} interface {{")
        for method in self._methods_of(symbol):
            lines.append(f"\t{pascal(method.name)}(args map[string]any) (any, error)")
        lines.append("}")
        return HEADER + "package interfaces\n\n" + "\n".join(lines) + "\n"

    # -- implementations -----------------------------------------------------

    def _implementation_module(self, symbol: ImplementationSymbol) -> str:
        class_name = self._class_name(symbol)
        interfaces = []
        for edge in self.graph.get_edges_from(symbol.id):
            if edge.kind == EdgeKind.IMPLEMENTS:
                target = self.graph.get_symbol(edge.target)
                if isinstance(target, InterfaceSymbol):
                    interfaces.append(target)
        interfaces = sorted(interfaces, key=lambda item: item.name)

        methods: Dict[str, MethodSymbol] = {}
        for interface in interfaces:
            for method in self._methods_of(interface):
                methods.setdefault(method.name, method)
        ordered = [methods[name] for name in sorted(methods)]

        imports: Set[str] = set()
        if interfaces:
            imports.add(f'"{self._module_path()}/interfaces"')
        if ordered:
            imports.add('"fmt"')

        lines = [f"// {class_name} is the SDL implementation {symbol.name}."]
        lines.append(f"type {class_name} struct{{}}")
        if interfaces:
            lines.append("")
            for interface in interfaces:
                lines.append(f"var _ interfaces.{interface.name} = (*{class_name})(nil)")
        for method in ordered:
            lines.append("")
            lines.append(
                f"func (instance *{class_name}) {pascal(method.name)}"
                f"(args map[string]any) (any, error) {{"
            )
            message = (
                f"The implementation {symbol.name} does not provide {method.name}. "
                f"Provide the file the specification declares, or bind another implementation."
            )
            lines.append(f"\treturn nil, fmt.Errorf({_string(message)})")
            lines.append("}")
        return HEADER + "package implementations\n\n" + self._import_block(imports) + "\n".join(lines) + "\n"

    def _module_module(self, module: str) -> str:
        functions = [
            function
            for function in self._module_functions()
            if function.metadata.get("scope") == module
        ]
        imports: Set[str] = set()
        if functions:
            imports.add('"fmt"')
        lines: List[str] = []
        for function in functions:
            lines.append(
                f"// {pascal(function.name)} is the function {function.name} "
                f"of the module {module}."
            )
            lines.append(
                f"func {pascal(function.name)}(args map[string]any) (any, error) {{"
            )
            message = (
                f"The module {module} does not provide {function.name}. "
                f"Provide the file the specification declares, or bind another implementation."
            )
            lines.append(f"\treturn nil, fmt.Errorf({_string(message)})")
            lines.append("}")
            lines.append("")
        body = "\n".join(lines) + "\n" if lines else ""
        return HEADER + "package implementations\n\n" + self._import_block(imports) + body

    # -- flows ---------------------------------------------------------------

    def _flow_module(self, symbol: FlowSymbol) -> str:
        imports: Set[str] = set()
        imports.add(f'"{self._module_path()}/runtime"')

        inputs = symbol.metadata.get("inputs", {})
        references = symbol.metadata.get("state_type_refs") or {}
        parameters = []
        for name in sorted(inputs):
            variable = symbol.state_definitions.get(name)
            type_id = variable.type_id if variable else None
            rendered = self._render_type(references.get(name), imports, type_id, prefix="types.")
            parameters.append(f"{go_local(name)} {rendered}")
        parameters.append("registry *runtime.Registry")

        steps = self._steps_of(symbol)
        outputs = symbol.metadata.get("outputs", {})
        output_mapping = symbol.metadata.get("output_mapping", {})

        lines = [
            HEADER,
            "package flows\n\n",
            self._import_block(imports),
            f"// {pascal(symbol.name)} is the SDL flow {symbol.name}.\n",
            f"func {pascal(symbol.name)}({', '.join(parameters)}) (map[string]any, error) {{\n",
        ]

        if inputs:
            lines.append("\tstate := map[string]any{\n")
            for name in sorted(inputs):
                lines.append(f"\t\t{_string(name)}: {go_local(name)},\n")
            lines.append("\t}\n")
        else:
            lines.append("\tstate := map[string]any{}\n")

        if not steps:
            lines.append("\t_ = registry\n")
            lines.append("\treturn map[string]any{}, nil\n")
            lines.append("}\n")
            return "".join(lines)

        lines.append("\t_step := 0\n")
        lines.append("\tvar _result any\n")
        lines.append("\tvar err error\n")
        lines.append("\t_ = _result\n")
        lines.append(f"\tfor _step < {len(steps)} {{\n")
        for index, step in enumerate(steps):
            lines.append(f"\t\tif _step == {index} {{\n")
            for line in self._step_body(step, steps):
                lines.append(f"\t\t\t{line}\n" if line else "\n")
            lines.append("\t\t}\n")
        lines.append("\t}\n")

        for name in sorted(outputs):
            path = output_mapping.get(name)
            first = str(path).split(".")[0] if path is not None else "None"
            lines.append(f"\tif _, ok := state[{_string(first)}]; !ok {{\n")
            lines.append(
                f"\t\treturn nil, &runtime.MandatoryOutputError"
                f"{{OutputName: {_string(name)}, State: state}}\n"
            )
            lines.append("\t}\n")

        if outputs:
            lines.append("\treturn map[string]any{\n")
            for name in sorted(outputs):
                path = output_mapping.get(name)
                if path is None:
                    lines.append(f"\t\t{_string(name)}: nil,\n")
                else:
                    lines.append(f"\t\t{_string(name)}: {self._output_expression(path)},\n")
            lines.append("\t}, nil\n")
        else:
            lines.append("\treturn map[string]any{}, nil\n")
        lines.append("}\n")
        return "".join(lines)

    def _steps_of(self, flow: FlowSymbol) -> List[FlowStepSymbol]:
        steps = []
        for step_id in flow.metadata.get("step_order", []):
            step = self.graph.get_symbol(step_id)
            if isinstance(step, FlowStepSymbol):
                steps.append(step)
        return steps

    def _step_body(self, step: FlowStepSymbol, steps: List[FlowStepSymbol]) -> List[str]:
        lines: List[str] = []
        target = step.metadata.get("call_target", "")
        mapping = step.metadata.get("mapping", {}) or {}
        output_map = step.metadata.get("output_map", {}) or {}
        condition = step.metadata.get("condition")
        on_error = step.metadata.get("on_error") or "fail"
        retry = step.metadata.get("retry") or {}

        lines.append(f"// step {step.name}")

        indent = ""
        if condition:
            try:
                expression = render_go(parse_condition(condition))
            except ConditionSyntaxError:
                expression = "true"
            lines.append(f"if {expression} {{")
            indent = "\t"

        arguments = ", ".join(
            f"{_string(parameter)}: {self._state_expression(path)}"
            for parameter, path in mapping.items()
        )
        arguments = "map[string]any{" + arguments + "}" if arguments else "map[string]any{}"

        if on_error == "retry":
            call = (
                f"_result, err = runtime.CallWithRetry(registry, {_string(target)}, "
                f"runtime.RetryPolicy{{Attempts: {int(retry.get('attempts', 1) or 1)}, "
                f"Backoff: {_string(retry.get('backoff') or 'fixed')}, "
                f"InitialInterval: {_float(retry.get('initial_interval'))}, "
                f"MaxInterval: {_float(retry.get('max_interval'))}}}, "
                f"{arguments})"
            )
        else:
            call = f"_result, err = runtime.Call(registry, {_string(target)}, {arguments})"

        if on_error == "ignore":
            lines.append(f"{indent}{call}")
            lines.append(f"{indent}if err != nil {{")
            lines.append(f"{indent}\t_result = nil")
            lines.append(f"{indent}}} else {{")
            for variable, path in output_map.items():
                lines.append(
                    f"{indent}\tstate[{_string(variable)}] = {self._output_expression(path)}"
                )
            lines.append(f"{indent}}}")
        elif on_error.startswith("goto "):
            index = self._step_index(steps, on_error[5:].strip())
            lines.append(f"{indent}{call}")
            lines.append(f"{indent}if err != nil {{")
            lines.append(f"{indent}\t_step = {index}")
            lines.append(f"{indent}\tcontinue")
            lines.append(f"{indent}}}")
            for variable, path in output_map.items():
                lines.append(f"{indent}state[{_string(variable)}] = {self._output_expression(path)}")
        else:
            lines.append(f"{indent}{call}")
            lines.append(f"{indent}if err != nil {{")
            lines.append(f"{indent}\treturn nil, err")
            lines.append(f"{indent}}}")
            for variable, path in output_map.items():
                lines.append(f"{indent}state[{_string(variable)}] = {self._output_expression(path)}")

        if condition:
            lines.append("}")

        # The step advances when it succeeds. The goto strategy jumps away
        # before this line, so the two paths do not conflict.
        lines.append(f"_step = {self._step_index(steps, step.name) + 1}")

        return lines

    def _step_index(self, steps: List[FlowStepSymbol], name: str) -> int:
        for index, step in enumerate(steps):
            if step.name == name:
                return index
        return 0

    def _state_expression(self, path: str) -> str:
        parts = str(path).split(".")
        rendered = f"state[{_string(parts[0])}]"
        for part in parts[1:]:
            rendered = f"runtime.Field({rendered}, {_string(part)})"
        return rendered

    def _output_expression(self, path: str) -> str:
        parts = str(path).split(".")
        if parts[0] == "result":
            rendered = "_result"
        else:
            rendered = f"state[{_string(parts[0])}]"
        for part in parts[1:]:
            rendered = f"runtime.Field({rendered}, {_string(part)})"
        return rendered

    # -- entry point and project files ---------------------------------------

    def _main_module(self) -> str:
        project = self._project()
        name = project.name if project else "application"
        flows = self._symbols(FlowSymbol)

        imports: Set[str] = {'"fmt"'}
        imports.add(f'"{self._module_path()}/runtime"')
        registrations: List[str] = []
        uses_implementations = False

        for interface, implementation in self._bindings():
            symbol_id = self.graph.resolve_symbol(implementation)
            symbol = self.graph.get_symbol(symbol_id) if symbol_id else None
            if symbol is None:
                continue
            uses_implementations = True
            class_name = self._class_name(symbol)
            registrations.append(
                f"\tregistry.Register({_string(interface)}, &implementations.{class_name}{{}})\n"
            )

        for function in self._module_functions():
            uses_implementations = True
            registrations.append(
                f"\tregistry.Register({_string(function.qualified_name)}, "
                f"implementations.{pascal(function.name)})\n"
            )

        if uses_implementations:
            imports.add(f'"{self._module_path()}/implementations"')

        lines = [
            HEADER,
            "package main\n\n",
            self._import_block(imports),
            "func buildRegistry() *runtime.Registry {\n",
            "\tregistry := runtime.NewRegistry()\n",
        ]
        lines.extend(registrations)
        lines.append("\treturn registry\n")
        lines.append("}\n")
        lines.append("\n")
        lines.append("func main() {\n")
        lines.append("\tregistry := buildRegistry()\n")
        lines.append("\t_ = registry\n")
        lines.append(f"\tfmt.Println({_string(f'The project {name} was compiled.')})\n")
        if flows:
            lines.append(f"\tfmt.Println({_string('The flows of the project:')})\n")
            for flow in flows:
                arguments = ", ".join(sorted(flow.metadata.get("inputs", {})))
                lines.append(f"\tfmt.Println({_string(f'  {flow.name}({arguments})')})\n")
        lines.append("}\n")
        return "".join(lines)

    # -- runtime modules -----------------------------------------------------

    def _registry_module(self) -> str:
        return '''package runtime

import "strconv"

// Registry holds the callables a flow names.
//
// A flow never imports a concrete implementation. It names the interface or
// the function of the specification, and the registry resolves that name to
// the implementation the bindings of the project chose.
type Registry struct {
	items map[string]any
}

// NewRegistry makes an empty registry.
func NewRegistry() *Registry {
	return &Registry{items: map[string]any{}}
}

// Register binds a name to its implementation.
func (r *Registry) Register(name string, implementation any) {
	r.items[name] = implementation
}

// Has reports whether a name is registered.
func (r *Registry) Has(name string) bool {
	_, ok := r.items[name]
	return ok
}

// Resolve returns the implementation of a name.
func (r *Registry) Resolve(name string) (any, error) {
	value, ok := r.items[name]
	if !ok {
		return nil, &UnknownTargetError{Message: "Nothing is registered for " +
			strconv.Quote(name) + ". The bindings of the project must provide it."}
	}
	return value, nil
}
'''

    def _errors_module(self) -> str:
        return '''package runtime

import "strconv"

// FlowError is the base error of a flow.
type FlowError struct {
	Message string
}

// Error renders the message of the error.
func (e *FlowError) Error() string {
	return e.Message
}

// UnknownTargetError is raised when a step names something that is not registered.
type UnknownTargetError struct {
	Message string
}

// Error renders the message of the error.
func (e *UnknownTargetError) Error() string {
	return e.Message
}

// StepFailed is raised when a step failed and its strategy does not recover.
type StepFailed struct {
	Message string
}

// Error renders the message of the error.
func (e *StepFailed) Error() string {
	return e.Message
}

// MandatoryOutputError is raised when a mandatory output is missing.
type MandatoryOutputError struct {
	OutputName string
	State      any
}

// Error renders the message of the error.
func (e *MandatoryOutputError) Error() string {
	return "The mandatory output " + strconv.Quote(e.OutputName) + " could not be populated."
}
'''

    def _dispatch_module(self) -> str:
        return '''package runtime

import (
	"reflect"
	"strconv"
	"strings"
	"time"
)

// RetryPolicy is the retry policy of a step.
type RetryPolicy struct {
	Attempts        int
	Backoff         string
	InitialInterval float64
	MaxInterval     float64
}

// exported turns the name a step writes into the name of a Go method.
func exported(name string) string {
	parts := strings.FieldsFunc(name, func(character rune) bool {
		return character == '_' || character == '-' || character == '.'
	})
	for index, part := range parts {
		parts[index] = strings.ToUpper(part[:1]) + part[1:]
	}
	return strings.Join(parts, "")
}

// resolveTarget is the callable a target names.
//
// Specification section 6.2: when a module calls a method of an interface, the
// runtime uses the bindings table to determine which concrete code to execute.
// So ``Checker::check`` is resolved to the method of the implementation the
// project bound to ``Checker``.
func resolveTarget(registry *Registry, target string) (reflect.Value, error) {
	if registry.Has(target) {
		value, _ := registry.Resolve(target)
		return reflect.ValueOf(value), nil
	}
	owner, member, found := strings.Cut(target, "::")
	if found && registry.Has(owner) {
		implementation, _ := registry.Resolve(owner)
		method := reflect.ValueOf(implementation).MethodByName(exported(member))
		if method.IsValid() {
			return method, nil
		}
	}
	value, err := registry.Resolve(target)
	if err != nil {
		return reflect.Value{}, err
	}
	return reflect.ValueOf(value), nil
}

func invoke(method reflect.Value, args map[string]any) (any, error) {
	values := method.Call([]reflect.Value{reflect.ValueOf(args)})
	if len(values) == 2 && !values[1].IsNil() {
		return nil, values[1].Interface().(error)
	}
	if len(values) >= 1 {
		return values[0].Interface(), nil
	}
	return nil, nil
}

// Call invokes the target of a step.
func Call(registry *Registry, target string, args map[string]any) (any, error) {
	method, err := resolveTarget(registry, target)
	if err != nil {
		return nil, err
	}
	return invoke(method, args)
}

// CallWithRetry calls the target of a step, repeating it per the retry policy.
//
// Attempts is the total number of attempts, the first one included.
func CallWithRetry(registry *Registry, target string, policy RetryPolicy, args map[string]any) (any, error) {
	delay := policy.InitialInterval
	attempts := policy.Attempts
	if attempts < 1 {
		attempts = 1
	}
	var failure error
	for attempt := 1; attempt <= attempts; attempt++ {
		result, err := Call(registry, target, args)
		if err == nil {
			return result, nil
		}
		failure = err
		if attempt >= attempts {
			break
		}
		if delay > 0 {
			time.Sleep(time.Duration(delay * float64(time.Second)))
		}
		if policy.Backoff == "exponential" {
			delay = delay * 2
			if delay > policy.MaxInterval {
				delay = policy.MaxInterval
			}
		} else if policy.Backoff == "linear" {
			delay = delay + policy.InitialInterval
			if delay > policy.MaxInterval {
				delay = policy.MaxInterval
			}
		}
	}
	return nil, &StepFailed{Message: "The step calling " + strconv.Quote(target) +
		" failed after " + strconv.Itoa(attempts) + " attempt(s): " + failure.Error()}
}
'''

    def _values_module(self) -> str:
        return '''package runtime

import "reflect"

// Field reads a named field of a value, for a path of the Flow State.
//
// The Flow State is a map of dynamic values, so a path such as
// ``payment_result.success`` cannot be a Go field selector. The runtime reads
// the field by reflection instead.
func Field(value any, name string) any {
	if value == nil {
		return nil
	}
	current := reflect.ValueOf(value)
	for current.Kind() == reflect.Pointer {
		if current.IsNil() {
			return nil
		}
		current = current.Elem()
	}
	if current.Kind() != reflect.Struct {
		return nil
	}
	field := current.FieldByName(exported(name))
	if !field.IsValid() || !field.CanInterface() {
		return nil
	}
	return field.Interface()
}

// Truth coerces a value to a boolean, for a condition of a flow.
func Truth(value any) bool {
	if value == nil {
		return false
	}
	boolean, ok := value.(bool)
	if ok {
		return boolean
	}
	return true
}

// Compare orders two dynamic values of a flow condition.
func Compare(left any, right any, operator string) bool {
	leftNumber, leftIsNumber := asFloat(left)
	rightNumber, rightIsNumber := asFloat(right)
	if leftIsNumber && rightIsNumber {
		return ordered(leftNumber, rightNumber, operator)
	}
	leftText, leftIsText := left.(string)
	rightText, rightIsText := right.(string)
	if leftIsText && rightIsText {
		return ordered(leftText, rightText, operator)
	}
	return false
}

func asFloat(value any) (float64, bool) {
	switch number := value.(type) {
	case int:
		return float64(number), true
	case int32:
		return float64(number), true
	case int64:
		return float64(number), true
	case float32:
		return float64(number), true
	case float64:
		return number, true
	}
	return 0, false
}

func ordered[T int | int64 | float64 | string](left T, right T, operator string) bool {
	switch operator {
	case ">":
		return left > right
	case "<":
		return left < right
	case ">=":
		return left >= right
	case "<=":
		return left <= right
	}
	return false
}
'''

    def _result_module(self) -> str:
        return '''package runtime

// Result is either a value of type T, or an error of type E.
type Result[T any, E any] struct {
	OK    bool
	Value T
	Err   E
}
'''

    # -- project files -------------------------------------------------------

    def _go_mod(self) -> str:
        return f"module {self._module_path()}\n\ngo 1.21\n"

    def _readme(self) -> str:
        project = self._project()
        name = project.name if project else "application"
        lines = [
            f"# {name}",
            "",
            "This application was generated from the SDL specification.",
            "",
            "## Layout",
            "",
            "| Path | Contents |",
            "| :--- | :--- |",
            "| `types/` | the compound types of the specification |",
            "| `interfaces/` | the contracts of the specification |",
            "| `implementations/` | the realizations of the contracts |",
            "| `flows/` | the business logic |",
            "| `runtime/` | the registry and the dispatcher the flows use |",
            "",
            "## Building",
            "",
            "The generated application needs nothing but the Go standard library.",
            "",
            "```powershell",
            "go build ./...",
            "```",
            "",
        ]
        return "\n".join(lines)
