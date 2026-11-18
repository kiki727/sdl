"""The Python back end.

Specification section 7.1: the generator creates complete source files in
the target language. The output is deterministic: the same canonical IR always
produces the same files, byte for byte.

The generated application has four parts:

* the **types**, the compound types of the specification, as dataclasses;
* the **interfaces**, the contracts of the specification, as protocols;
* the **flows**, the business logic, as async functions with an explicit
  data flow;
* the **runtime**, the small amount of machinery the flows need: a registry
  that resolves a name to an implementation, and a dispatcher that calls it.

A flow never imports a concrete implementation. It names the interface or the
function of the specification, and the registry resolves the name through the
bindings of the project. That is what makes the implementation replaceable
without touching the business logic.

Nothing the document wrote is ever copied into the generated source as raw
text. A condition is parsed and rendered, a type is mapped to a Python type,
and a name is rendered as a string literal.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from sdl.flow.expressions import ConditionSyntaxError, parse_condition, render_python
from sdl.ir.edges import EdgeKind
from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import (
    FlowStepSymbol,
    FlowSymbol,
    ImplementationSymbol,
    InterfaceSymbol,
    MethodSymbol,
    ProjectSymbol,
    Symbol,
    TypeKind,
    TypeSymbol,
)

HEADER = '"""{summary}\n\nDo not edit: this file is generated from the SDL specification.\n"""\n'

#: The standard library modules the built-in types need.
STDLIB = ("decimal", "datetime", "uuid")

#: How a built-in type is written in Python, and the import it needs.
SCALARS: Dict[str, tuple[str, str | None]] = {
    "String": ("str", None),
    "Int": ("int", None),
    "Float": ("float", None),
    "Decimal": ("Decimal", "from decimal import Decimal"),
    "Boolean": ("bool", None),
    "UUID": ("UUID", "from uuid import UUID"),
    "Date": ("date", "from datetime import date"),
    "DateTime": ("datetime", "from datetime import datetime"),
    "Bytes": ("bytes", None),
    "Unit": ("None", None),
    "List": ("List", "from typing import List"),
    "Map": ("Dict", "from typing import Dict"),
    "Optional": ("Optional", "from typing import Optional"),
    "Result": ("Result", "from ..runtime.result import Result"),
}

#: The built-in types that take type arguments.
GENERIC_BUILTINS = ("List", "Map", "Optional", "Result")


def snake(name: str) -> str:
    """``PaymentRequest`` becomes ``payment_request``."""
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return text.replace("-", "_").replace(".", "_").lower()


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


class PythonCodegen:
    """Generates a Python application from the canonical IR."""

    def __init__(self, graph: SymbolGraph):
        self.graph = graph

    # -- entry point ---------------------------------------------------------

    def generate(self) -> Dict[str, str]:
        """The generated files, keyed by their path relative to the output root."""
        files: Dict[str, str] = {}

        files["src/__init__.py"] = self._package_init()
        files["src/types/__init__.py"] = self._types_init()
        files["src/interfaces/__init__.py"] = self._interfaces_init()
        files["src/implementations/__init__.py"] = self._implementations_init()
        files["src/flows/__init__.py"] = self._flows_init()
        files["src/runtime/__init__.py"] = self._runtime_init()

        files["src/runtime/registry.py"] = self._registry_module()
        files["src/runtime/errors.py"] = self._errors_module()
        files["src/runtime/dispatch.py"] = self._dispatch_module()
        files["src/runtime/result.py"] = self._result_module()

        for symbol in self._declared_types():
            files[f"src/types/{snake(symbol.name)}.py"] = self._type_module(symbol)

        for symbol in self._symbols(InterfaceSymbol):
            files[f"src/interfaces/{snake(symbol.name)}.py"] = self._interface_module(symbol)

        for symbol in self._symbols(ImplementationSymbol):
            files[f"src/implementations/{snake(symbol.name)}.py"] = self._implementation_module(symbol)

        for module in self._modules():
            files[f"src/implementations/{snake(module)}.py"] = self._module_module(module)

        for symbol in self._symbols(FlowSymbol):
            files[f"src/flows/{snake(symbol.name)}.py"] = self._flow_module(symbol)

        files["main.py"] = self._main_module()
        files["pyproject.toml"] = self._pyproject()
        files["requirements.txt"] = self._requirements()
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

    def _project(self) -> ProjectSymbol | None:
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

    # -- typing --------------------------------------------------------------

    def _python_type(
        self,
        type_id: Any,
        imports: Set[str],
        arguments: List[Any] | None = None,
    ) -> str:
        """The Python type of a symbol, collecting the imports it needs.

        A generic built-in keeps its arguments, so that ``Result<Payment,
        Error>`` becomes ``Result[Payment, Error]`` and not ``Any``.
        """
        if type_id is None:
            return "Any"

        symbol = self.graph.get_symbol(type_id)
        if symbol is None:
            return "Any"

        if not isinstance(symbol, TypeSymbol):
            return "Any"

        if symbol.metadata.get("builtin"):
            entry = SCALARS.get(symbol.name)
            if entry is None:
                return "Any"
            rendered, statement = entry
            if statement:
                imports.add(statement)
            if symbol.name in GENERIC_BUILTINS and arguments:
                rendered = (
                    f"{rendered}["
                    + ", ".join(
                        self._python_type(argument, imports) for argument in arguments
                    )
                    + "]"
                )
            return rendered

        imports.add(f"from ..types.{snake(symbol.name)} import {symbol.name}")
        return symbol.name

    def _class_of_module(self, module_name: str) -> str:
        for symbol in self._declared_types():
            if snake(symbol.name) == module_name:
                return symbol.name
        return "".join(part.capitalize() for part in module_name.split("_"))

    def _import_block(self, imports: Set[str], extra: List[str] | None = None) -> str:
        """The whole import block of a generated module.

        The statements are grouped the way the style guide wants them: the
        standard library first, then the modules of the generated package.
        """
        stdlib = sorted(
            statement
            for statement in imports
            if not statement.startswith("from ..")
        )
        local = sorted(
            statement for statement in imports if statement.startswith("from ..")
        )
        if extra:
            stdlib.extend(
                statement for statement in extra if not statement.startswith("from ..")
            )
            local.extend(
                statement for statement in extra if statement.startswith("from ..")
            )
            stdlib = sorted(set(stdlib))
            local = sorted(set(local))

        lines: List[str] = list(stdlib)
        if stdlib and local:
            lines.append("")
        lines.extend(local)
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def _type_name(self, type_id: Any) -> str:
        symbol = self.graph.get_symbol(type_id) if type_id else None
        return symbol.name if symbol is not None else "Any"

    # -- package files -------------------------------------------------------

    def _package_init(self) -> str:
        project = self._project()
        name = project.name if project else "application"
        return (
            f'"""The generated application {name}.\n\n'
            "Do not edit: this file is generated from the SDL specification.\n"
            '"""\n'
        )

    def _types_init(self) -> str:
        lines = [
            '"""The types of the specification.\n\n'
            "Do not edit: this file is generated from the SDL specification.\n"
            '"""\n'
        ]
        for symbol in self._declared_types():
            lines.append(f"from .{snake(symbol.name)} import {symbol.name}")
        return "\n".join(lines) + "\n"

    def _interfaces_init(self) -> str:
        lines = [
            '"""The contracts of the specification.\n\n'
            "Do not edit: this file is generated from the SDL specification.\n"
            '"""\n'
        ]
        for symbol in self._symbols(InterfaceSymbol):
            lines.append(f"from .{snake(symbol.name)} import {symbol.name}")
        return "\n".join(lines) + "\n"

    def _implementations_init(self) -> str:
        lines = [
            '"""The implementations of the specification.\n\n'
            "Do not edit: this file is generated from the SDL specification.\n"
            '"""\n'
        ]
        for symbol in self._symbols(ImplementationSymbol):
            lines.append(f"from .{snake(symbol.name)} import {self._class_name(symbol)}")
        for module in self._modules():
            for function in self._module_functions():
                if function.metadata.get("scope") == module:
                    lines.append(f"from .{snake(module)} import {function.name}")
        return "\n".join(lines) + "\n"

    def _flows_init(self) -> str:
        lines = [
            '"""The flows of the specification.\n\n'
            "Do not edit: this file is generated from the SDL specification.\n"
            '"""\n'
        ]
        for symbol in self._symbols(FlowSymbol):
            lines.append(f"from .{snake(symbol.name)} import {symbol.name}")
        return "\n".join(lines) + "\n"

    def _runtime_init(self) -> str:
        return (
            '"""The runtime the generated flows use.\n\n'
            "Do not edit: this file is generated from the SDL specification.\n"
            '"""\n'
        )

    # -- runtime modules -----------------------------------------------------

    def _registry_module(self) -> str:
        return '''"""The registry of the callables of the project.

Do not edit: this file is generated from the SDL specification.
"""
from typing import Any, Dict

from .errors import UnknownTargetError


class Registry:
    """Holds the callables a flow names.

    A flow never imports a concrete implementation. It names the interface or
    the function of the specification, and the registry resolves that name to
    the implementation the bindings of the project chose.
    """

    def __init__(self) -> None:
        self._items: Dict[str, Any] = {}

    def register(self, name: str, implementation: Any) -> None:
        """Register the implementation of a name."""
        self._items[name] = implementation

    def resolve(self, name: str) -> Any:
        """The implementation of a name."""
        try:
            return self._items[name]
        except KeyError:
            raise UnknownTargetError(
                f"Nothing is registered for {name!r}. The bindings of the project "
                f"must provide it."
            ) from None

    def __contains__(self, name: str) -> bool:
        return name in self._items
'''

    def _errors_module(self) -> str:
        return '''"""The errors the generated runtime raises.

Do not edit: this file is generated from the SDL specification.
"""
from typing import Any


class FlowError(Exception):
    """The base class of every error of a flow."""


class UnknownTargetError(FlowError):
    """A step names something that is not registered."""


class StepFailed(FlowError):
    """A step failed and its error strategy does not recover from it."""


class MandatoryOutputError(FlowError):
    """A mandatory output of a flow could not be populated."""

    def __init__(self, name: str, state: Any = None):
        super().__init__(f"The mandatory output {name!r} could not be populated.")
        self.name = name
        self.state = state
'''

    def _dispatch_module(self) -> str:
        return '''"""Calling the targets of a flow.

Do not edit: this file is generated from the SDL specification.
"""
import asyncio
from typing import Any

from .errors import StepFailed
from .registry import Registry


def resolve_target(registry: Registry, target: str) -> Any:
    """The callable a target names.

    Specification section 6.2: when a module calls a method of an interface,
    the runtime uses the bindings table to determine which concrete code to
    execute. So ``Checker::check`` is resolved to the method of the
    implementation the project bound to ``Checker``.
    """
    if target in registry:
        return registry.resolve(target)
    owner, separator, member = target.partition("::")
    if separator and owner in registry:
        implementation = registry.resolve(owner)
        method = getattr(implementation, member, None)
        if method is not None:
            return method
    return registry.resolve(target)


async def call(registry: Registry, target: str, **arguments: Any) -> Any:
    """Call the target of a step and await it when it is asynchronous."""
    implementation = resolve_target(registry, target)
    result = implementation(**arguments)
    if asyncio.iscoroutine(result):
        result = await result
    return result


async def call_with_retry(
    registry: Registry,
    target: str,
    *,
    attempts: int = 1,
    backoff: str = "fixed",
    initial_interval: float = 1.0,
    max_interval: float = 30.0,
    **arguments: Any,
) -> Any:
    """Call the target of a step, repeating it according to the retry policy.

    ``attempts`` is the total number of attempts, the first one included.
    """
    delay = initial_interval
    failure: Any = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return await call(registry, target, **arguments)
        except Exception as error:  # noqa: BLE001 - the policy decides what happens
            failure = error
            if attempt >= attempts:
                break
            if delay > 0:
                await asyncio.sleep(delay)
            if backoff == "exponential":
                delay = min(delay * 2, max_interval)
            elif backoff == "linear":
                delay = min(delay + initial_interval, max_interval)
    raise StepFailed(
        f"The step calling {target!r} failed after {attempts} attempt(s): {failure}"
    ) from failure
'''

    def _result_module(self) -> str:
        return '''"""The result of a call that may fail.

Do not edit: this file is generated from the SDL specification.
"""
from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")


class Result(Generic[T, E]):
    """Either a value of type T, or an error of type E."""

    def __init__(self, value: T = None, error: E = None) -> None:
        self.value = value
        self.error = error

    @property
    def is_ok(self) -> bool:
        """Whether the call succeeded."""
        return self.error is None

    def __repr__(self) -> str:
        if self.is_ok:
            return f"Result.ok({self.value!r})"
        return f"Result.error({self.error!r})"
'''

    # -- types ---------------------------------------------------------------

    def _type_module(self, symbol: TypeSymbol) -> str:
        summary = f"The SDL type {symbol.name}."
        imports: Set[str] = set()

        if symbol.type_kind == TypeKind.ENUM:
            body = self._enum_body(symbol)
            extra = ["from enum import Enum"]
        elif symbol.type_kind == TypeKind.ALIAS:
            body = self._alias_body(symbol)
            extra = []
        else:
            body = self._dataclass_body(symbol)
            extra = ["from dataclasses import dataclass"]

        body_lines = body(imports)
        block = self._import_block(imports, extra)
        return HEADER.format(summary=summary) + block + "\n" + body_lines

    def _dataclass_body(self, symbol: TypeSymbol):
        def build(imports: Set[str]) -> str:
            lines = [
                "",
                "",
                "@dataclass",
                f"class {symbol.name}:",
                f'    """The SDL type {symbol.name}."""',
                "",
            ]
            if not symbol.fields:
                lines.append("    pass")
                return "\n".join(lines) + "\n"
            arguments_of = symbol.metadata.get("field_type_arguments", {})
            for field in symbol.fields:
                rendered = self._python_type(
                    field.type_id, imports, arguments_of.get(field.name)
                )
                lines.append(f"    {field.name}: {rendered}")
            return "\n".join(lines) + "\n"

        return build

    def _alias_body(self, symbol: TypeSymbol):
        def build(imports: Set[str]) -> str:
            target = symbol.metadata.get("alias_target")
            rendered = self._python_type(target, imports) if target else "Any"
            lines = [
                "",
                "",
                f"{symbol.name} = {rendered}",
                f'"""The SDL alias {symbol.name}."""',
                "",
            ]
            return "\n".join(lines) + "\n"

        return build

    def _enum_body(self, symbol: TypeSymbol):
        def build(imports: Set[str]) -> str:
            lines = [
                "",
                "",
                f"class {symbol.name}(Enum):",
                f'    """The SDL enum {symbol.name}."""',
                "",
            ]
            values = list(symbol.metadata.get("enum_values", []))
            if not values:
                lines.append("    pass")
                return "\n".join(lines) + "\n"
            for value in values:
                lines.append(f'    {value.upper()} = "{value}"')
            return "\n".join(lines) + "\n"

        return build

    # -- interfaces ----------------------------------------------------------

    def _interface_module(self, symbol: InterfaceSymbol) -> str:
        summary = f"The SDL interface {symbol.name}."
        imports: Set[str] = set()
        methods = self._methods_of(symbol)

        signatures = []
        for method in methods:
            parameters = ["self"]
            for parameter in method.parameters:
                rendered = self._python_type(
                    parameter.type_id, imports, parameter.type_arguments
                )
                parameters.append(f"{parameter.name}: {rendered}")
            returns = self._python_type(
                method.return_type_id,
                imports,
                method.metadata.get("return_type_arguments"),
            )
            signatures.append((method, parameters, returns))

        block = self._import_block(imports, ["from typing import Any, Protocol"])

        lines = [HEADER.format(summary=summary), block, "", ""]
        lines.append(f"class {symbol.name}(Protocol):")
        lines.append(f'    """The contract of the SDL interface {symbol.name}."""')
        lines.append("")
        if not signatures:
            lines.append("    ...")
            return "\n".join(lines) + "\n"

        for method, parameters, returns in signatures:
            lines.append(f"    def {method.name}({', '.join(parameters)}) -> {returns}:")
            lines.append(f'        """The method {method.name} of {symbol.name}."""')
            lines.append("        ...")
            lines.append("")

        return "\n".join(lines) + "\n"

    # -- implementations -----------------------------------------------------

    def _class_name(self, symbol: ImplementationSymbol) -> str:
        source = symbol.metadata.get("source") or {}
        name = source.get("symbol")
        return name if isinstance(name, str) and name else symbol.name

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
            parameters = ["self"]
            for parameter in method.parameters:
                rendered = self._python_type(
                    parameter.type_id, imports, parameter.type_arguments
                )
                parameters.append(f"{parameter.name}: {rendered}")
            returns = self._python_type(
                method.return_type_id,
                imports,
                method.metadata.get("return_type_arguments"),
            )
            signatures.append((method, parameters, returns))

        extra = [f"from ..interfaces.{snake(interface.name)} import {interface.name}" for interface in interfaces]
        block = self._import_block(imports, extra)

        lines = [HEADER.format(summary=summary), block, "", ""]
        lines.append(f"class {self._class_name(symbol)}:")
        lines.append(f'    """The realization of the SDL implementation {symbol.name}.')
        lines.append("")
        if source_file:
            lines.append(f"    The specification declares the realization in")
            lines.append(f"    {source_file} as {source_symbol}.")
        else:
            lines.append("    The specification does not declare a source file for it.")
        lines.append('    """')
        lines.append("")

        if not signatures:
            lines.append("    pass")
            return "\n".join(lines) + "\n"

        for method, parameters, returns in signatures:
            lines.append(f"    def {method.name}({', '.join(parameters)}) -> {returns}:")
            lines.append(f'        """The method {method.name}."""')
            lines.append("        raise NotImplementedError(")
            lines.append(
                f'            "The implementation {symbol.name} does not provide '
                f'{method.name}. "'
            )
            lines.append(
                '            "Provide the file the specification declares, or bind another '
                'implementation."'
            )
            lines.append("        )")
            lines.append("")

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
            parameters = []
            for parameter in function.parameters:
                rendered = self._python_type(
                    parameter.type_id, imports, parameter.type_arguments
                )
                parameters.append(f"{parameter.name}: {rendered}")
            returns = self._python_type(
                function.return_type_id,
                imports,
                function.metadata.get("return_type_arguments"),
            )
            signatures.append((function, parameters, returns))

        block = self._import_block(imports, ["from typing import Any"])
        lines = [HEADER.format(summary=summary), block, ""]
        for function, parameters, returns in signatures:
            lines.append("")
            lines.append(f"def {function.name}({', '.join(parameters)}) -> {returns}:")
            lines.append(f'    """The function {function.name} of the module {module}."""')
            lines.append("    raise NotImplementedError(")
            lines.append(
                f'        "The module {module} does not provide {function.name}. "'
            )
            lines.append(
                '        "Provide the file the specification declares, or bind another '
                'implementation."'
            )
            lines.append("    )")
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
            rendered = self._python_type(type_id, imports)
            parameters.append(f"{name}: {rendered}")

        block = self._import_block(
            imports,
            [
                "from typing import Any, Dict",
                "from ..runtime.dispatch import call, call_with_retry",
                "from ..runtime.errors import MandatoryOutputError",
                "from ..runtime.registry import Registry",
            ],
        )

        lines = [HEADER.format(summary=summary), block, "", ""]
        signature = ", ".join(parameters + ["*", "registry: Registry"])
        lines.append(f"async def {symbol.name}({signature}) -> Dict[str, Any]:")
        lines.append(f'    """The SDL flow {symbol.name}."""')
        lines.append("    state: Dict[str, Any] = {")
        for name in sorted(inputs):
            lines.append(f"        {name!r}: {name},")
        lines.append("    }")
        lines.append("")

        steps = self._steps_of(symbol)
        if not steps:
            lines.append("    return {}")
            lines.append("")
            return "\n".join(lines) + "\n"

        lines.append("    _step = 0")
        lines.append(f"    while _step < {len(steps)}:")
        for index, step in enumerate(steps):
            lines.append(f"        if _step == {index}:")
            for line in self._step_body(step, steps):
                lines.append(f"            {line}" if line else "")
        lines.append("")

        outputs = symbol.metadata.get("outputs", {})
        output_mapping = symbol.metadata.get("output_mapping", {})
        if outputs:
            lines.append("    for _name, _path in (")
            for name in sorted(outputs):
                path = output_mapping.get(name)
                lines.append(f"        ({name!r}, {str(path)!r}),")
            lines.append("    ):")
            lines.append("        if _path.split('.')[0] not in state:")
            lines.append("            raise MandatoryOutputError(_name, state)")
            lines.append("")

        lines.append("    return {")
        for name in sorted(outputs):
            path = output_mapping.get(name)
            if path is None:
                lines.append(f"        {name!r}: None,")
            else:
                lines.append(f"        {name!r}: {self._state_expression(path)},")
        lines.append("    }")
        lines.append("")
        return "\n".join(lines) + "\n"

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
        mapping = step.metadata.get("mapping", {})
        output_map = step.metadata.get("output_map", {})
        condition = step.metadata.get("condition")
        on_error = step.metadata.get("on_error") or "fail"
        retry = step.metadata.get("retry") or {}

        lines.append(f"# step {step.name}")

        outer = ""
        indent = ""
        if condition:
            try:
                expression = render_python(parse_condition(condition))
            except ConditionSyntaxError:
                expression = "True"
            lines.append(f"if {expression}:")
            indent = "    "

        arguments = ", ".join(
            f"{parameter}={self._state_expression(path)}" for parameter, path in mapping.items()
        )

        if on_error == "retry":
            call = (
                f"_result = await call_with_retry(registry, {target!r}, "
                f"attempts={retry.get('attempts', 1)}, "
                f"backoff={(retry.get('backoff') or 'fixed')!r}, "
                f"initial_interval={_seconds(retry.get('initial_interval'))}, "
                f"max_interval={_seconds(retry.get('max_interval'))}, "
                f"{arguments})"
            )
        else:
            call = f"_result = await call(registry, {target!r}, {arguments})"

        lines.append(f"{indent}try:")
        lines.append(f"{indent}    {call}")

        if on_error == "ignore":
            lines.append(f"{indent}except Exception:  # noqa: BLE001 - the strategy is 'ignore'")
            lines.append(f"{indent}    _result = None")
            lines.append(f"{indent}else:")
            for variable, path in output_map.items():
                lines.append(f"{indent}    state[{variable!r}] = {self._output_expression(path)}")
        elif on_error.startswith("goto "):
            index = self._step_index(steps, on_error[5:].strip())
            lines.append(f"{indent}except Exception:  # noqa: BLE001 - the strategy is 'goto'")
            lines.append(f"{indent}    _step = {index}")
            lines.append(f"{indent}    continue")
            for variable, path in output_map.items():
                lines.append(f"{indent}state[{variable!r}] = {self._output_expression(path)}")
        else:
            lines.append(f"{indent}except Exception:")
            lines.append(f"{indent}    raise")
            for variable, path in output_map.items():
                lines.append(f"{indent}state[{variable!r}] = {self._output_expression(path)}")

        if condition:
            lines.append(f"{outer}else:")
            lines.append(f"{outer}    pass")

        # The step advances when it succeeds. The goto strategy jumps away
        # before this line, so the two paths do not conflict.
        lines.append(f"{outer}_step = {self._step_index(steps, step.name) + 1}")

        return lines

    def _step_index(self, steps: List[FlowStepSymbol], name: str) -> int:
        for index, step in enumerate(steps):
            if step.name == name:
                return index
        return 0

    def _state_expression(self, path: str) -> str:
        parts = str(path).split(".")
        rendered = f"state[{parts[0]!r}]"
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
        lines = [
            f'"""The entry point of the generated application {name}.',
            "",
            "Do not edit: this file is generated from the SDL specification.",
            '"""\n',
            "import asyncio\n",
        ]
        if flows:
            lines.append(
                "from src.flows import " + ", ".join(flow.name for flow in flows) + "\n"
            )
        lines.append("from src.runtime.registry import Registry\n")

        imports: List[str] = []
        registrations: List[str] = []

        for interface, implementation in self._bindings():
            symbol_id = self.graph.resolve_symbol(implementation)
            symbol = self.graph.get_symbol(symbol_id) if symbol_id else None
            if symbol is None:
                continue
            class_name = self._class_name(symbol)
            imports.append(
                f"from src.implementations.{snake(symbol.name)} import {class_name}"
            )
            registrations.append(f'    registry.register({interface!r}, {class_name}())')

        for function in self._module_functions():
            imports.append(
                f"from src.implementations.{snake(str(function.metadata['scope']))} "
                f"import {function.name}"
            )
            registrations.append(
                f"    registry.register({function.qualified_name!r}, {function.name})"
            )

        for statement in sorted(set(imports)):
            lines.append(statement + "\n")

        lines.append("")
        lines.append("")
        lines.append("def build_registry() -> Registry:")
        lines.append('    """The registry of the project, built from its bindings."""')
        lines.append("    registry = Registry()")
        for registration in registrations:
            lines.append(registration)
        lines.append("    return registry")
        lines.append("")
        lines.append("")
        lines.append("async def main() -> None:")
        lines.append(f'    """The flows of {name}."""')
        lines.append("    registry = build_registry()")
        lines.append(f'    print(f"The project {name} was compiled.")')
        if flows:
            lines.append('    print("The flows of the project:")')
            for flow in flows:
                arguments = ", ".join(sorted(flow.metadata.get("inputs", {})))
                lines.append(f'    print(f"  {flow.name}({arguments})")')
        lines.append("")
        lines.append("")
        lines.append('if __name__ == "__main__":')
        lines.append("    asyncio.run(main())")
        lines.append("")
        return "\n".join(lines)

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

    def _pyproject(self) -> str:
        project = self._project()
        name = snake(project.name) if project else "application"
        return f'''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "0.1.0"
description = "Generated from the SDL specification."
requires-python = ">=3.10"
dependencies = []

[tool.setuptools]
packages = ["src"]
'''

    def _requirements(self) -> str:
        return "# The generated application needs no third party package.\n"

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
            "```powershell",
            "python main.py",
            "```",
            "",
        ]
        return "\n".join(lines)
