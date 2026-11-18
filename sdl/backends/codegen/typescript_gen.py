"""The NodeJS/TypeScript back end.

Specification section 7.1: the generator creates complete source files in the
target language. The output is deterministic: the same canonical IR always
produces the same files, byte for byte.

The generated application has four parts:

* the **types**, the compound types of the specification, as interfaces;
* the **interfaces**, the contracts of the specification, as interfaces;
* the **flows**, the business logic, as async functions with an explicit
  data flow;
* the **runtime**, the small amount of machinery the flows need: a registry
  that resolves a name to an implementation, and a dispatcher that calls it.

A flow never imports a concrete implementation. It names the interface or the
function of the specification, and the registry resolves the name through the
bindings of the project. That is what makes the implementation replaceable
without touching the business logic.

Two things are specific to the language. JavaScript has no keyword arguments,
so the inputs of a method travel as a single object, the way the runtime calls
it. And a TypeScript file is written to be **erasable**: no `enum`, no
`namespace`, no parameter property, and every import of a type is an
`import type`. Node can therefore run the generated source directly, which is
what the test suite does.

Nothing the document wrote is ever copied into the generated source as raw
text. A condition is parsed and rendered, a type is mapped to a TypeScript
type, and a name is rendered as a string literal.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

from sdl.flow.expressions import (
    ConditionSyntaxError,
    parse_condition,
    render_typescript,
)
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

HEADER = (
    "/**\n"
    " * {summary}\n"
    " *\n"
    " * Do not edit: this file is generated from the SDL specification.\n"
    " */\n"
)

#: How a built-in type is written in TypeScript.
SCALARS: Dict[str, str] = {
    "String": "string",
    "Int": "number",
    "Float": "number",
    "Decimal": "number",
    "Boolean": "boolean",
    "UUID": "string",
    "Date": "string",
    "DateTime": "string",
    "Bytes": "Uint8Array",
    "Unit": "null",
}

#: The built-in types that take type arguments.
GENERIC_BUILTINS = ("List", "Map", "Optional", "Result")

RESULT_IMPORT = 'import type { Result } from "../runtime/result.ts";'


def snake(name: str) -> str:
    """``PaymentRequest`` becomes ``payment_request``."""
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return text.replace("-", "_").replace(".", "_").lower()


def _string(value: Any) -> str:
    """A value as a TypeScript string literal, escaped by the JSON writer."""
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


class TypeScriptCodegen:
    """Generates a NodeJS/TypeScript application from the canonical IR."""

    def __init__(self, graph: SymbolGraph):
        self.graph = graph

    # -- entry point ---------------------------------------------------------

    def generate(self) -> Dict[str, str]:
        """The generated files, keyed by their path relative to the output root."""
        files: Dict[str, str] = {}

        files["src/runtime/registry.ts"] = self._registry_module()
        files["src/runtime/errors.ts"] = self._errors_module()
        files["src/runtime/dispatch.ts"] = self._dispatch_module()
        files["src/runtime/result.ts"] = self._result_module()

        for symbol in self._declared_types():
            files[f"src/types/{snake(symbol.name)}.ts"] = self._type_module(symbol)

        for symbol in self._symbols(InterfaceSymbol):
            files[f"src/interfaces/{snake(symbol.name)}.ts"] = self._interface_module(symbol)

        for symbol in self._symbols(ImplementationSymbol):
            files[f"src/implementations/{snake(symbol.name)}.ts"] = self._implementation_module(symbol)

        for module in self._modules():
            files[f"src/implementations/{snake(module)}.ts"] = self._module_module(module)

        for symbol in self._symbols(FlowSymbol):
            files[f"src/flows/{snake(symbol.name)}.ts"] = self._flow_module(symbol)

        files["main.ts"] = self._main_module()
        files["package.json"] = self._package_json()
        files["tsconfig.json"] = self._tsconfig()
        files["README.md"] = self._readme()
        return files

    # -- graph access --------------------------------------------------------

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
        return name if isinstance(name, str) and name else symbol.name

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
    ) -> str:
        """The TypeScript type of a resolved reference.

        The reference carries the shape of a generic or a union, so a nested
        ``List<Optional<String>>`` keeps its arguments. When there is no
        reference, the flat identifier and its arguments are used, which is
        enough for a name or a single level of generic.
        """
        if reference is not None:
            return self._render_reference(reference, imports)
        return self._render_flat(type_id, imports, arguments or [])

    def _render_reference(self, reference: TypeRef, imports: Set[str]) -> str:
        if reference.kind == "union":
            members = [self._render_reference(item, imports) for item in reference.arguments]
            return " | ".join(members) if members else "any"
        if reference.kind == "generic":
            symbol = self.graph.get_symbol(reference.base) if reference.base else None
            name = symbol.name if symbol is not None else "any"
            rendered = [self._render_reference(item, imports) for item in reference.arguments]
            return self._generic(name, rendered, imports)
        symbol = self.graph.get_symbol(reference.base) if reference.base else None
        return self._named(symbol, imports)

    def _render_flat(self, type_id: Any, imports: Set[str], arguments: List[Any]) -> str:
        if type_id is None:
            return "any"
        symbol = self.graph.get_symbol(type_id)
        if symbol is None:
            return "any"
        if not isinstance(symbol, TypeSymbol):
            return "any"
        rendered = [self._render_flat(item, imports, []) for item in arguments]
        if symbol.metadata.get("builtin"):
            if symbol.name in GENERIC_BUILTINS and rendered:
                return self._generic(symbol.name, rendered, imports)
            return SCALARS.get(symbol.name, "any")
        return self._named(symbol, imports)

    def _named(self, symbol: Optional[TypeSymbol], imports: Set[str]) -> str:
        if symbol is None:
            return "any"
        if symbol.metadata.get("builtin"):
            return SCALARS.get(symbol.name, "any")
        if symbol.name == "Result":
            imports.add(RESULT_IMPORT)
            return "Result"
        imports.add(
            f'import type {{ {symbol.name} }} from "../types/{snake(symbol.name)}.ts";'
        )
        return symbol.name

    def _generic(self, name: str, arguments: List[str], imports: Set[str]) -> str:
        if name == "Optional":
            inner = arguments[0] if arguments else "any"
            return f"{inner} | null"
        if name == "List":
            inner = arguments[0] if arguments else "any"
            if " | " in inner:
                inner = f"({inner})"
            return f"{inner}[]"
        if name == "Map":
            key = arguments[0] if arguments else "string"
            value = arguments[1] if len(arguments) > 1 else "any"
            return f"Record<{key}, {value}>"
        if name == "Result":
            imports.add(RESULT_IMPORT)
            inner = ", ".join(arguments) if arguments else "any, any"
            return f"Result<{inner}>"
        return f"{name}<{', '.join(arguments)}>" if arguments else name

    def _input_object(self, method: MethodSymbol, imports: Set[str]) -> str:
        """The single object the inputs of a method travel in.

        JavaScript has no keyword arguments, so a method that the specification
        gives several inputs takes one object, with the inputs as its fields.
        """
        if not method.parameters:
            return "Record<string, never>"
        parts = []
        for parameter in method.parameters:
            rendered = self._render_type(
                parameter.type_ref, imports, parameter.type_id, parameter.type_arguments
            )
            optional = "?" if parameter.optional else ""
            parts.append(f"{parameter.name}{optional}: {rendered}")
        return "{ " + "; ".join(parts) + " }"

    def _return_type(self, method: MethodSymbol, imports: Set[str]) -> str:
        return self._render_type(
            method.metadata.get("return_type_ref"),
            imports,
            method.return_type_id,
            method.metadata.get("return_type_arguments"),
        )

    def _import_block(self, imports: Set[str], extra: Optional[List[str]] = None) -> str:
        statements = set(imports)
        if extra:
            statements.update(extra)
        if not statements:
            return ""
        return "\n".join(sorted(statements)) + "\n"

    # -- types ---------------------------------------------------------------

    def _type_module(self, symbol: TypeSymbol) -> str:
        summary = f"The SDL type {symbol.name}."
        imports: Set[str] = set()
        if symbol.type_kind == TypeKind.ENUM:
            body = self._enum_body(symbol)
        elif symbol.type_kind == TypeKind.ALIAS:
            body = self._alias_body(symbol, imports)
        else:
            body = self._interface_body(symbol, imports)
        block = self._import_block(imports)
        return HEADER.format(summary=summary) + block + "\n" + body

    def _interface_body(self, symbol: TypeSymbol, imports: Set[str]) -> str:
        lines = ["", f"export interface {symbol.name} {{"]
        if not symbol.fields:
            lines.append("}")
            return "\n".join(lines) + "\n"
        # The resolved identifier of a field is its base type, and the
        # arguments of a generic are kept beside it. The shape of the reference
        # is not kept for a field, so the flat pair is used, as the Python back
        # end does.
        arguments_of = symbol.metadata.get("field_type_arguments", {})
        for field in symbol.fields:
            rendered = self._render_type(
                None,
                imports,
                field.type_id,
                arguments_of.get(field.name),
            )
            optional = "?" if field.optional else ""
            lines.append(f"  {field.name}{optional}: {rendered};")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def _alias_body(self, symbol: TypeSymbol, imports: Set[str]) -> str:
        rendered = self._render_type(
            symbol.metadata.get("alias_type_ref"),
            imports,
            symbol.metadata.get("alias_target"),
        )
        return "\n" + f"export type {symbol.name} = {rendered};\n"

    def _enum_body(self, symbol: TypeSymbol) -> str:
        values = [str(value) for value in symbol.metadata.get("enum_values", [])]
        lines = [""]
        if values:
            lines.append(
                f"export type {symbol.name} = "
                + " | ".join(json.dumps(value, ensure_ascii=False) for value in values)
                + ";"
            )
            lines.append("")
            lines.append(f"export const {symbol.name} = {{")
            for value in values:
                lines.append(f"  {_string(value.upper())}: {_string(value)},")
            lines.append("} as const;")
        else:
            lines.append(f"export type {symbol.name} = string;")
        return "\n".join(lines) + "\n"

    # -- interfaces ----------------------------------------------------------

    def _interface_module(self, symbol: InterfaceSymbol) -> str:
        summary = f"The SDL interface {symbol.name}."
        imports: Set[str] = set()
        signatures = []
        for method in self._methods_of(symbol):
            signatures.append(
                (method, self._input_object(method, imports), self._return_type(method, imports))
            )
        block = self._import_block(imports)
        lines = [HEADER.format(summary=summary), block, "", f"export interface {symbol.name} {{"]
        for method, inputs, returns in signatures:
            lines.append(f"  {method.name}(input: {inputs}): Promise<{returns}>;")
        lines.append("}")
        return "\n".join(lines) + "\n"

    # -- implementations -----------------------------------------------------

    def _implementation_module(self, symbol: ImplementationSymbol) -> str:
        summary = f"The SDL implementation {symbol.name}."
        source = symbol.metadata.get("source") or {}
        source_file = source.get("file")
        source_symbol = source.get("symbol")

        interfaces = []
        for edge in self.graph.get_edges_from(symbol.id):
            if edge.kind == EdgeKind.IMPLEMENTS:
                target = self.graph.get_symbol(edge.target)
                if isinstance(target, InterfaceSymbol):
                    interfaces.append(target)
        interfaces = sorted(interfaces, key=lambda item: item.name)

        implemented: List[MethodSymbol] = []
        for interface in interfaces:
            implemented.extend(self._methods_of(interface))

        imports: Set[str] = set()
        signatures = []
        for method in sorted(implemented, key=lambda item: item.name):
            signatures.append(
                (method, self._input_object(method, imports), self._return_type(method, imports))
            )

        extra = [
            f'import type {{ {interface.name} }} from "../interfaces/{snake(interface.name)}.ts";'
            for interface in interfaces
        ]
        block = self._import_block(imports, extra)

        implements = (
            " implements " + ", ".join(interface.name for interface in interfaces)
            if interfaces
            else ""
        )
        lines = [HEADER.format(summary=summary), block, ""]
        lines.append(f"export class {self._class_name(symbol)}{implements} {{")
        if not signatures:
            lines.append("}")
            return "\n".join(lines) + "\n"
        for method, inputs, returns in signatures:
            lines.append(f"  async {method.name}(input: {inputs}): Promise<{returns}> {{")
            lines.append("    throw new Error(")
            lines.append(
                f"      {_string(f'The implementation {symbol.name} does not provide {method.name}. ')} +"
            )
            lines.append(
                '        "Provide the file the specification declares, or bind another implementation."'
            )
            lines.append("    );")
            lines.append("  }")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def _module_module(self, module: str) -> str:
        summary = f"The SDL module {module}."
        imports: Set[str] = set()
        functions = [
            function
            for function in self._module_functions()
            if function.metadata.get("scope") == module
        ]
        signatures = []
        for function in functions:
            signatures.append(
                (function, self._input_object(function, imports), self._return_type(function, imports))
            )
        block = self._import_block(imports)
        lines = [HEADER.format(summary=summary), block, ""]
        for function, inputs, returns in signatures:
            lines.append(f"export async function {function.name}(input: {inputs}): Promise<{returns}> {{")
            lines.append("  throw new Error(")
            lines.append(
                f"    {_string(f'The module {module} does not provide {function.name}. ')} +"
            )
            lines.append(
                '      "Provide the file the specification declares, or bind another implementation."'
            )
            lines.append("  );")
            lines.append("}")
            lines.append("")
        return "\n".join(lines)

    # -- flows ---------------------------------------------------------------

    def _flow_module(self, symbol: FlowSymbol) -> str:
        summary = f"The SDL flow {symbol.name}."
        imports: Set[str] = set()

        inputs = symbol.metadata.get("inputs", {})
        parameters = []
        for name in sorted(inputs):
            variable = symbol.state_definitions.get(name)
            type_id = variable.type_id if variable else None
            rendered = self._render_type(None, imports, type_id)
            parameters.append(f"{name}: {rendered}")
        parameters.append("registry: Registry")

        block = self._import_block(
            imports,
            [
                'import { call, call_with_retry } from "../runtime/dispatch.ts";',
                'import { MandatoryOutputError } from "../runtime/errors.ts";',
                'import type { Registry } from "../runtime/registry.ts";',
            ],
        )

        lines = [HEADER.format(summary=summary), block, ""]
        lines.append(
            f"export async function {symbol.name}({', '.join(parameters)}): Promise<Record<string, any>> {{"
        )
        lines.append("  const state: Record<string, any> = {")
        for name in sorted(inputs):
            lines.append(f"    {_string(name)}: {name},")
        lines.append("  };")
        lines.append("  let _result: any;")
        lines.append("")

        steps = self._steps_of(symbol)
        if steps:
            lines.append("  let _step = 0;")
            lines.append(f"  while (_step < {len(steps)}) {{")
            for index, step in enumerate(steps):
                lines.append(f"    if (_step === {index}) {{")
                for line in self._step_body(step, steps):
                    lines.append(f"      {line}" if line else "")
                lines.append("    }")
            lines.append("  }")
            lines.append("")

        outputs = symbol.metadata.get("outputs", {})
        output_mapping = symbol.metadata.get("output_mapping", {})
        for name in sorted(outputs):
            path = output_mapping.get(name)
            first = str(path).split(".")[0] if path is not None else "None"
            lines.append(f"  if (!({_string(first)} in state)) {{")
            lines.append(f"    throw new MandatoryOutputError({_string(name)}, state);")
            lines.append("  }")
        if outputs:
            lines.append("")

        lines.append("  return {")
        for name in sorted(outputs):
            path = output_mapping.get(name)
            if path is None:
                lines.append(f"    {_string(name)}: null,")
            else:
                lines.append(f"    {_string(name)}: {self._state_expression(path)},")
        lines.append("  };")
        lines.append("}")
        lines.append("")
        return "\n".join(lines)

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
                expression = render_typescript(parse_condition(condition))
            except ConditionSyntaxError:
                expression = "true"
            lines.append(f"if ({expression}) {{")
            indent = "  "

        arguments = ", ".join(
            f"{_string(parameter)}: {self._state_expression(path)}"
            for parameter, path in mapping.items()
        )
        arguments = "{ " + arguments + " }" if arguments else "{}"

        if on_error == "retry":
            call = (
                f"_result = await call_with_retry(registry, {_string(target)}, "
                f"{{ attempts: {int(retry.get('attempts', 1) or 1)}, "
                f"backoff: {_string(retry.get('backoff') or 'fixed')}, "
                f"initialInterval: {_seconds(retry.get('initial_interval'))}, "
                f"maxInterval: {_seconds(retry.get('max_interval'))} }}, "
                f"{arguments});"
            )
        else:
            call = f"_result = await call(registry, {_string(target)}, {arguments});"

        if on_error == "ignore":
            lines.append(f"{indent}try {{")
            lines.append(f"{indent}  {call}")
            for variable, path in output_map.items():
                lines.append(f"{indent}  state[{_string(variable)}] = {self._output_expression(path)};")
            lines.append(f"{indent}}} catch {{")
            lines.append(f"{indent}  _result = null;")
            lines.append(f"{indent}}}")
        elif on_error.startswith("goto "):
            index = self._step_index(steps, on_error[5:].strip())
            lines.append(f"{indent}try {{")
            lines.append(f"{indent}  {call}")
            lines.append(f"{indent}}} catch {{")
            lines.append(f"{indent}  _step = {index};")
            lines.append(f"{indent}  continue;")
            lines.append(f"{indent}}}")
            for variable, path in output_map.items():
                lines.append(f"{indent}state[{_string(variable)}] = {self._output_expression(path)};")
        else:
            lines.append(f"{indent}{call}")
            for variable, path in output_map.items():
                lines.append(f"{indent}state[{_string(variable)}] = {self._output_expression(path)};")

        if condition:
            lines.append("}")

        # The step advances when it succeeds. The goto strategy jumps away
        # before this line, so the two paths do not conflict.
        lines.append(f"_step = {self._step_index(steps, step.name) + 1};")

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
            rendered += f".{part}"
        return rendered

    def _output_expression(self, path: str) -> str:
        parts = str(path).split(".")
        if parts[0] == "result":
            rendered = "_result"
            for part in parts[1:]:
                rendered += f".{part}"
            return rendered
        return self._state_expression(path)

    # -- entry point and project files ---------------------------------------

    def _main_module(self) -> str:
        project = self._project()
        name = project.name if project else "application"
        flows = self._symbols(FlowSymbol)
        lines = [HEADER.format(summary=f"The entry point of the generated application {name}."), ""]

        imports: List[str] = ['import { Registry } from "./src/runtime/registry.ts";']
        registrations: List[str] = []

        for interface, implementation in self._bindings():
            symbol_id = self.graph.resolve_symbol(implementation)
            symbol = self.graph.get_symbol(symbol_id) if symbol_id else None
            if symbol is None:
                continue
            class_name = self._class_name(symbol)
            imports.append(
                f'import {{ {class_name} }} from "./src/implementations/{snake(symbol.name)}.ts";'
            )
            registrations.append(f"  registry.register({_string(interface)}, new {class_name}());")

        for function in self._module_functions():
            imports.append(
                f'import {{ {function.name} }} from "./src/implementations/'
                f'{snake(str(function.metadata["scope"]))}.ts";'
            )
            registrations.append(
                f"  registry.register({_string(function.qualified_name)}, {function.name});"
            )

        for statement in sorted(set(imports)):
            lines.append(statement)
        lines.append("")
        lines.append("")
        lines.append("export function buildRegistry(): Registry {")
        lines.append("  const registry = new Registry();")
        lines.extend(registrations)
        lines.append("  return registry;")
        lines.append("}")
        lines.append("")
        lines.append("")
        lines.append("async function main(): Promise<void> {")
        lines.append("  const registry = buildRegistry();")
        lines.append(f"  console.log({_string(f'The project {name} was compiled.')});")
        lines.append(f"  console.log({_string('The flows of the project:')});")
        for flow in flows:
            arguments = ", ".join(sorted(flow.metadata.get("inputs", {})))
            lines.append(f"  console.log({_string(f'  {flow.name}({arguments})')});")
        lines.append("}")
        lines.append("")
        lines.append("")
        lines.append("await main();")
        lines.append("")
        return "\n".join(lines)

    # -- runtime modules -----------------------------------------------------

    def _registry_module(self) -> str:
        return '''/**
 * The registry of the callables of the project.
 *
 * Do not edit: this file is generated from the SDL specification.
 */
import { UnknownTargetError } from "./errors.ts";


export class Registry {
  private readonly items = new Map<string, unknown>();

  /** Register the implementation of a name. */
  register(name: string, implementation: unknown): void {
    this.items.set(name, implementation);
  }

  /** Whether a name is registered. */
  has(name: string): boolean {
    return this.items.has(name);
  }

  /** The implementation of a name. */
  resolve(name: string): unknown {
    if (!this.items.has(name)) {
      throw new UnknownTargetError(
        `Nothing is registered for ${JSON.stringify(name)}. The bindings of the project must provide it.`,
      );
    }
    return this.items.get(name);
  }
}
'''

    def _errors_module(self) -> str:
        return '''/**
 * The errors the generated runtime raises.
 *
 * Do not edit: this file is generated from the SDL specification.
 */


export class FlowError extends Error {}

/** A step names something that is not registered. */
export class UnknownTargetError extends FlowError {}

/** A step failed and its error strategy does not recover from it. */
export class StepFailed extends FlowError {}

/** A mandatory output of a flow could not be populated. */
export class MandatoryOutputError extends FlowError {
  readonly outputName: string;
  readonly state: unknown;

  constructor(outputName: string, state?: unknown) {
    super(`The mandatory output ${JSON.stringify(outputName)} could not be populated.`);
    this.outputName = outputName;
    this.state = state;
  }
}
'''

    def _dispatch_module(self) -> str:
        return '''/**
 * Calling the targets of a flow.
 *
 * Do not edit: this file is generated from the SDL specification.
 */
import { StepFailed } from "./errors.ts";
import type { Registry } from "./registry.ts";


type Callable = (...args: any[]) => any;

/**
 * The callable a target names.
 *
 * Specification section 6.2: when a module calls a method of an interface, the
 * runtime uses the bindings table to determine which concrete code to execute.
 * So ``Checker::check`` is resolved to the method of the implementation the
 * project bound to ``Checker``.
 */
export function resolveTarget(registry: Registry, target: string): Callable {
  if (registry.has(target)) {
    return registry.resolve(target) as Callable;
  }

  const separator = target.indexOf("::");
  if (separator >= 0) {
    const owner = target.slice(0, separator);
    const member = target.slice(separator + 2);
    if (registry.has(owner)) {
      const implementation = registry.resolve(owner) as Record<string, unknown>;
      const method = implementation[member];
      if (typeof method === "function") {
        return (method as Callable).bind(implementation);
      }
    }
  }

  return registry.resolve(target) as Callable;
}

/** Call the target of a step and await it. */
export async function call(
  registry: Registry,
  target: string,
  args: Record<string, unknown> = {},
): Promise<any> {
  const implementation = resolveTarget(registry, target);
  return await implementation(args);
}

/** The retry policy of a step. */
export interface RetryPolicy {
  attempts: number;
  backoff: string;
  initialInterval: number;
  maxInterval: number;
}

/**
 * Call the target of a step, repeating it according to the retry policy.
 *
 * ``attempts`` is the total number of attempts, the first one included.
 */
export async function call_with_retry(
  registry: Registry,
  target: string,
  policy: RetryPolicy,
  args: Record<string, unknown> = {},
): Promise<any> {
  let delay = policy.initialInterval;
  let failure: unknown = null;
  const attempts = Math.max(1, policy.attempts);
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await call(registry, target, args);
    } catch (error) {
      failure = error;
      if (attempt >= attempts) {
        break;
      }
      if (delay > 0) {
        await sleep(delay);
      }
      if (policy.backoff === "exponential") {
        delay = Math.min(delay * 2, policy.maxInterval);
      } else if (policy.backoff === "linear") {
        delay = Math.min(delay + policy.initialInterval, policy.maxInterval);
      }
    }
  }
  throw new StepFailed(
    `The step calling ${JSON.stringify(target)} failed after ${attempts} attempt(s): ${failure}`,
  );
}

function sleep(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}
'''

    def _result_module(self) -> str:
        return '''/**
 * The result of a call that may fail.
 *
 * Do not edit: this file is generated from the SDL specification.
 */


export interface Result<T, E> {
  readonly ok: boolean;
  readonly value?: T;
  readonly error?: E;
}
'''

    # -- project files -------------------------------------------------------

    def _package_json(self) -> str:
        project = self._project()
        name = snake(project.name).replace("_", "-") if project else "application"
        return (
            json.dumps(
                {
                    "name": name,
                    "version": "0.1.0",
                    "private": True,
                    "type": "module",
                    "description": "Generated from the SDL specification.",
                    "scripts": {"start": "node main.ts"},
                },
                indent=2,
            )
            + "\n"
        )

    def _tsconfig(self) -> str:
        return (
            json.dumps(
                {
                    "compilerOptions": {
                        "target": "es2022",
                        "module": "nodenext",
                        "moduleResolution": "nodenext",
                        "strict": True,
                        "noEmit": True,
                        "allowImportingTsExtensions": True,
                        "skipLibCheck": True,
                        "forceConsistentCasingInFileNames": True,
                    },
                    "include": ["src", "main.ts"],
                },
                indent=2,
            )
            + "\n"
        )

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
            "| `src/types/` | the compound types of the specification |",
            "| `src/interfaces/` | the contracts of the specification |",
            "| `src/implementations/` | the realizations of the contracts |",
            "| `src/flows/` | the business logic |",
            "| `src/runtime/` | the registry and the dispatcher the flows use |",
            "",
            "## Running",
            "",
            "Node runs the generated TypeScript directly, by stripping the types.",
            "",
            "```powershell",
            "node main.ts",
            "```",
            "",
            "To type check it, install TypeScript and run `tsc --noEmit`.",
            "",
        ]
        return "\n".join(lines)
