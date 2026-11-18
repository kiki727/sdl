"""Semantic analysis for SDL Core 1.0.

Core 1.0 inherits every document level rule from Core 0.2 and adds the rules
defined in `spec/sdl-core-1.0.md`:

* flow data-flow rules (section 2.3.3)
* flow output rules (section 2.2.1, 3.3.2)
* condition expression grammar (section 3.2.1)
* error handling and retry policy (section 3.3.1)
* architectural prohibitions (section 4.1)
* implementation and binding rules (section 6)

The Core 0.2 rules that still apply and are implemented here are: scope and
duplicate identifiers, name shadowing, import resolution and import cycles,
type expression resolution, alias cycles, generic arity, and the restrictions
on the ``Unit`` type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sdl.diagnostics import Report, json_pointer
from sdl.flow.expressions import variables
from sdl.schema.envelope import (
    normalize_import_path,
    validate_json_schema,
    validate_schema,
)
from sdl.types import expressions as sdl_types
from sdl.yaml.subset import ParsedDocument, SubsetError, location, node_at, parse_file

CORE_VERSION = "1.0"

#: Kinds whose root value is a mapping keyed by identifier.
_MAPPING_KINDS = ("types",)


# ---------------------------------------------------------------------------
# Documents and symbols
# ---------------------------------------------------------------------------


@dataclass
class Document:
    path: Path
    rel: str
    parsed: ParsedDocument
    kind: str | None
    id: str | None = None

    @property
    def root_value(self) -> Any:
        if self.kind is None:
            return None
        return self.parsed.data.get(self.kind)


@dataclass(eq=False)
class Symbol:
    name: str
    kind: str
    scope: "Scope"
    doc: Document
    parts: list[Any]
    expr: sdl_types.TypeExpr | None = None
    data: dict[str, Any] | None = None
    version: str | None = None
    fields: dict[str, sdl_types.TypeExpr] = field(default_factory=dict)
    methods: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Scope:
    name: str
    symbols: dict[str, Symbol] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Condition expression grammar (spec section 3.2.1)
# ---------------------------------------------------------------------------

_COMPARISON_OPERATORS = ("==", "!=", ">=", "<=", ">", "<")


from sdl.flow.expressions import ConditionSyntaxError, parse_condition as _parse_condition


def parse_condition(text: str) -> list[tuple[str, str, int]]:
    """Parse a condition and return the state variables it references."""
    node = _parse_condition(text)
    return [(name, name, 0) for name in variables(node)]


# ---------------------------------------------------------------------------
# Project context
# ---------------------------------------------------------------------------


class ProjectContext:
    """The semantic context of a Core 1.0 document set."""

    def __init__(self, start: Document, report: Report, schema: dict[str, Any]):
        self.start = start
        self.report = report
        self.schema = schema
        self.base_dir = start.path.parent
        self.documents: dict[Path, Document] = {start.path.resolve(): start}
        self.project_scope = Scope("project")
        self.module_scopes: dict[str, Scope] = {}
        self.visible: dict[str, set[str]] = {}

        self._load_imports(start)
        self._build_project_scope()
        self._build_module_scopes()
        self._check_shadowing()
        self._check_alias_cycles()
        self._check_class_recursion()
        self._check_flows()
        self._check_bindings()
        self._check_call_bindings()
        self._check_backend()

    # -- diagnostics --------------------------------------------------------

    def _diag(
        self,
        doc: Document,
        phase: str,
        severity: str,
        code: str,
        message: str,
        parts: list[Any],
    ) -> None:
        node = node_at(doc.parsed.root, parts)
        line, column = location(node)
        self.report.add(phase, severity, code, message, doc.rel, line, column, json_pointer(parts))

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.base_dir.resolve()).as_posix()
        except ValueError:
            return path.name

    # -- loading ------------------------------------------------------------

    def _load_imports(self, doc: Document) -> None:
        """Load and validate every document reachable through path imports."""
        queue: list[Document] = [doc]
        seen: set[Path] = {doc.path.resolve()}

        while queue:
            current = queue.pop(0)
            root = current.root_value
            if not isinstance(root, dict):
                continue
            imports = root.get("imports")
            if not isinstance(imports, list):
                continue

            for index, item in enumerate(imports):
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    continue
                normalized = normalize_import_path(item["path"])
                if normalized is None:
                    self._diag(
                        current,
                        "schema",
                        "error",
                        "SDL-E300",
                        "Invalid import path.",
                        [current.kind or "document", "imports", index, "path"],
                    )
                    continue

                target = (self.base_dir / normalized).resolve()
                try:
                    target.relative_to(self.base_dir.resolve())
                except ValueError:
                    self._diag(
                        current,
                        "schema",
                        "error",
                        "SDL-E300",
                        "Import path escapes the project root.",
                        [current.kind or "document", "imports", index, "path"],
                    )
                    continue

                if target in seen:
                    continue
                seen.add(target)

                if not target.exists():
                    self._diag(
                        current,
                        "semantic",
                        "error",
                        "SDL-E302",
                        "Imported file does not exist.",
                        [current.kind or "document", "imports", index, "path"],
                    )
                    continue

                try:
                    parsed = parse_file(target)
                except SubsetError as error:
                    self.report.add(
                        "syntax",
                        "error",
                        error.code,
                        error.message,
                        self._rel(target),
                        error.line,
                        error.column,
                    )
                    continue

                file_rel = self._rel(target)
                kind = validate_schema(parsed, file_rel, self.report)
                validate_json_schema(parsed, file_rel, self.report, self.schema)
                if kind is None:
                    continue

                doc_id = None
                root_value = parsed.data.get(kind)
                if isinstance(root_value, dict) and isinstance(root_value.get("id"), str):
                    doc_id = root_value["id"]

                imported = Document(target, file_rel, parsed, kind, doc_id)
                self.documents[target] = imported
                queue.append(imported)

    # -- scope --------------------------------------------------------------

    def _build_project_scope(self) -> None:
        for doc in self.documents.values():
            root = doc.root_value
            if doc.kind == "project" and isinstance(root, dict):
                self._add_types(doc, root.get("types"), ["project", "types"])
                self._add_interfaces(doc, root.get("interfaces"), ["project", "interfaces"])
            elif doc.kind == "types" and isinstance(root, dict):
                self._add_types_mapping(doc, root, ["types"])
            elif doc.kind == "interface" and isinstance(root, dict):
                self._add_interface(doc, root, ["interface"])

    def _build_module_scopes(self) -> None:
        """A module has a scope of its own, next to the project scope."""
        for doc in self.documents.values():
            if doc.kind != "module":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            module_id = root.get("id")
            if not isinstance(module_id, str):
                continue
            if module_id in self.module_scopes:
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E211",
                    f"Duplicate module ID {module_id!r}.",
                    ["module", "id"],
                )
                continue

            scope = Scope(module_id)
            self.module_scopes[module_id] = scope
            self._add_types(doc, root.get("types"), ["module", "types"], scope)
            self._add_interfaces(doc, root.get("interfaces"), ["module", "interfaces"], scope)
            self._add_classes(doc, root.get("classes"), ["module", "classes"], scope)

    def _scope_for(self, doc: Document) -> Scope:
        """The scope a declaration of a document belongs to."""
        if doc.kind == "module" and isinstance(doc.id, str):
            scope = self.module_scopes.get(doc.id)
            if scope is not None:
                return scope
        return self.project_scope

    def _add_types_mapping(self, doc: Document, value: dict[str, Any], prefix: list[Any]) -> None:
        for name, declaration in value.items():
            if not isinstance(declaration, dict):
                continue
            parts = prefix + [name]
            self._add_type_declaration(doc, name, declaration, parts)

    def _add_types(
        self,
        doc: Document,
        value: Any,
        prefix: list[Any],
        scope: Scope | None = None,
    ) -> None:
        if not isinstance(value, list):
            return
        for index, declaration in enumerate(value):
            if not isinstance(declaration, dict):
                continue
            name = declaration.get("id")
            if not isinstance(name, str):
                continue
            self._add_type_declaration(doc, name, declaration, prefix + [index], scope)

    def _add_types_mapping(self, doc: Document, value: dict[str, Any], prefix: list[Any]) -> None:
        for name, declaration in value.items():
            if not isinstance(declaration, dict):
                continue
            parts = prefix + [name]
            self._add_type_declaration(doc, name, declaration, parts)

    def _add_type_declaration(
        self,
        doc: Document,
        name: str,
        declaration: dict[str, Any],
        parts: list[Any],
        scope: Scope | None = None,
    ) -> None:
        target_scope = scope if scope is not None else self._scope_for(doc)
        if "enum" in declaration:
            symbol = Symbol(name, "enum", target_scope, doc, parts, data=declaration)
            self._check_enum_values(doc, declaration, parts)
        elif "type" in declaration:
            expression = None
            if isinstance(declaration["type"], str):
                try:
                    expression = sdl_types.parse(declaration["type"])
                except sdl_types.TypeSyntaxError:
                    expression = None
            symbol = Symbol(name, "alias", target_scope, doc, parts, expr=expression, data=declaration)
        else:
            symbol = Symbol(name, "compound", target_scope, doc, parts, data=declaration)
            for field_name, field_type in (declaration.get("fields") or {}).items():
                if not isinstance(field_type, str):
                    continue
                try:
                    symbol.fields[field_name] = sdl_types.parse(field_type)
                except sdl_types.TypeSyntaxError:
                    continue

        symbol.version = declaration.get("version") if isinstance(declaration.get("version"), str) else None
        self._add_symbol(symbol, target_scope)

    def _add_classes(
        self,
        doc: Document,
        value: Any,
        prefix: list[Any],
        scope: Scope,
    ) -> None:
        if not isinstance(value, list):
            return
        for index, declaration in enumerate(value):
            if not isinstance(declaration, dict):
                continue
            name = declaration.get("id")
            if not isinstance(name, str):
                continue
            symbol = Symbol(name, "class", scope, doc, prefix + [index], data=declaration)
            self._add_symbol(symbol, scope)

    def _add_interfaces(
        self,
        doc: Document,
        value: Any,
        prefix: list[Any],
        scope: Scope | None = None,
    ) -> None:
        if not isinstance(value, list):
            return
        for index, interface in enumerate(value):
            if isinstance(interface, dict):
                self._add_interface(doc, interface, prefix + [index], scope)

    def _add_interface(
        self,
        doc: Document,
        interface: dict[str, Any],
        parts: list[Any],
        scope: Scope | None = None,
    ) -> None:
        name = interface.get("id")
        if not isinstance(name, str):
            return
        target_scope = scope if scope is not None else self._scope_for(doc)
        methods: list[dict[str, Any]] = []
        raw_methods = interface.get("methods")
        if isinstance(raw_methods, list):
            for index, method in enumerate(raw_methods):
                if isinstance(method, dict):
                    methods.append(method)
        symbol = Symbol(
            name,
            "interface",
            target_scope,
            doc,
            parts,
            data=interface,
            version=interface.get("version") if isinstance(interface.get("version"), str) else None,
            methods=methods,
        )
        self._add_symbol(symbol, target_scope)

    def _add_symbol(self, symbol: Symbol, scope: Scope) -> None:
        if symbol.name in sdl_types.BUILTINS:
            self._diag(
                symbol.doc,
                "semantic",
                "error",
                "SDL-E211",
                f"Builtin type {symbol.name!r} must not be redeclared.",
                symbol.parts + ["id"],
            )
            return
        existing = scope.symbols.get(symbol.name)
        if existing is not None:
            if existing.doc is symbol.doc:
                self._diag(
                    symbol.doc,
                    "semantic",
                    "error",
                    "SDL-E211",
                    f"Duplicate ID {symbol.name!r} in scope {scope.name!r}.",
                    symbol.parts + ["id"],
                )
            else:
                self._diag(
                    symbol.doc,
                    "semantic",
                    "error",
                    "SDL-E213",
                    f"ID {symbol.name!r} shadows an identifier declared in "
                    f"{existing.doc.rel}.",
                    symbol.parts + ["id"],
                )
            return
        scope.symbols[symbol.name] = symbol

    def _check_enum_values(self, doc: Document, declaration: dict[str, Any], parts: list[Any]) -> None:
        values = declaration.get("enum")
        if not isinstance(values, list):
            return
        seen: set[str] = set()
        for index, value in enumerate(values):
            if not isinstance(value, str):
                continue
            if value in seen:
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E211",
                    f"Duplicate enum value {value!r}.",
                    parts + ["enum", index],
                )
            seen.add(value)

    def _check_shadowing(self) -> None:
        """A declaration may not shadow an identifier of another document.

        The project scope is shared by every document reachable from the root
        project document, so a type declared by a `types` document and the same
        type declared by the project document itself are a shadowing error.
        Identifiers declared twice inside the same scope are reported as
        duplicates by `_add_symbol`.
        """
        for doc in self.documents.values():
            if doc.kind != "types":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            for name in root:
                symbol = self.project_scope.symbols.get(name)
                if symbol is not None and symbol.doc is not doc:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E213",
                        f"Type ID {name!r} shadows an identifier declared in "
                        f"{symbol.doc.rel}.",
                        ["types", name, "id"],
                    )

        # A module identifier may not shadow a project identifier.
        for module_id in self.module_scopes:
            symbol = self.project_scope.symbols.get(module_id)
            if symbol is None:
                continue
            for doc in self.documents.values():
                if doc.kind != "module" or doc.id != module_id:
                    continue
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E213",
                    f"Module ID {module_id!r} shadows a project ID.",
                    ["module", "id"],
                )

    # -- type resolution ----------------------------------------------------

    def _all_symbols(self) -> Iterable[Symbol]:
        yield from self.project_scope.symbols.values()
        for scope in self.module_scopes.values():
            yield from scope.symbols.values()

    def _resolve(self, name: str, scope: Scope | None = None) -> tuple[Symbol | None, str | None]:
        """Resolve a type name in a scope, then in the project scope."""
        if "::" in name:
            scope_name, type_name = name.split("::", 1)
            if scope_name == "project":
                return self.project_scope.symbols.get(type_name), None
            module_scope = self.module_scopes.get(scope_name)
            if module_scope is not None:
                return module_scope.symbols.get(type_name), None
            return None, "unknown_scope"
        if scope is not None:
            symbol = scope.symbols.get(name)
            if symbol is not None:
                return symbol, None
        return self.project_scope.symbols.get(name), None

    @staticmethod
    def _names(expression: sdl_types.TypeExpr | None) -> Iterable[sdl_types.TypeName]:
        if expression is None:
            return
        if isinstance(expression, sdl_types.TypeName):
            yield expression
        elif isinstance(expression, sdl_types.TypeGeneric):
            for argument in expression.args:
                yield from ProjectContext._names(argument)
        elif isinstance(expression, sdl_types.TypeUnion):
            for item in expression.items:
                yield from ProjectContext._names(item)

    def _check_alias_cycles(self) -> None:
        aliases = [symbol for symbol in self._all_symbols() if symbol.kind == "alias"]
        graph: dict[Symbol, list[Symbol]] = {symbol: [] for symbol in aliases}
        for symbol in aliases:
            for name in self._names(symbol.expr):
                target, _ = self._resolve(name.name, symbol.scope)
                if target is not None and target.kind == "alias":
                    graph[symbol].append(target)

        state: dict[Symbol, int] = {}
        stack: list[Symbol] = []

        def visit(symbol: Symbol) -> None:
            state[symbol] = 1
            stack.append(symbol)
            for target in graph.get(symbol, []):
                if state.get(target, 0) == 0:
                    visit(target)
                elif state.get(target) == 1 and target in stack:
                    start = stack.index(target)
                    for cycle_symbol in stack[start:]:
                        self._diag(
                            cycle_symbol.doc,
                            "semantic",
                            "error",
                            "SDL-E402",
                            f"Cyclic alias involving {cycle_symbol.name!r}.",
                            cycle_symbol.parts + ["type"],
                        )
            stack.pop()
            state[symbol] = 2

        for symbol in aliases:
            if state.get(symbol, 0) == 0:
                visit(symbol)

    def _check_class_recursion(self) -> None:
        """Compound types may not contain themselves directly."""
        compounds = [symbol for symbol in self._all_symbols() if symbol.kind == "compound"]
        graph: dict[Symbol, list[Symbol]] = {symbol: [] for symbol in compounds}
        for symbol in compounds:
            for expression in symbol.fields.values():
                for name in self._names(expression):
                    target, _ = self._resolve(name.name, symbol.scope)
                    if target is not None and target.kind == "compound":
                        graph[symbol].append(target)

        state: dict[Symbol, int] = {}
        stack: list[Symbol] = []

        def visit(symbol: Symbol) -> None:
            state[symbol] = 1
            stack.append(symbol)
            for target in graph.get(symbol, []):
                if state.get(target, 0) == 0:
                    visit(target)
                elif state.get(target) == 1 and target in stack:
                    start = stack.index(target)
                    for cycle_symbol in stack[start:]:
                        self._diag(
                            cycle_symbol.doc,
                            "semantic",
                            "error",
                            "SDL-E403",
                            f"Direct class recursion involving {cycle_symbol.name!r}.",
                            cycle_symbol.parts + ["fields"],
                        )
            stack.pop()
            state[symbol] = 2

        for symbol in compounds:
            if state.get(symbol, 0) == 0:
                visit(symbol)

    # -- flows (spec sections 2 and 3) --------------------------------------

    def _check_flows(self) -> None:
        for doc in self.documents.values():
            if doc.kind != "flow":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            self._check_flow(doc, root)

    def _check_flow(self, doc: Document, root: dict[str, Any]) -> None:
        parts = ["flow"]
        inputs = root.get("inputs") if isinstance(root.get("inputs"), dict) else {}
        outputs = root.get("outputs") if isinstance(root.get("outputs"), dict) else {}
        output_mapping = root.get("output_mapping")
        steps = root.get("steps") if isinstance(root.get("steps"), list) else []

        # 2.2.1 output_mapping is mandatory when outputs are declared.
        if outputs and not isinstance(output_mapping, dict):
            self._diag(
                doc,
                "semantic",
                "error",
                "SDL-E503",
                "output_mapping is mandatory for a flow that declares outputs.",
                parts + ["outputs"],
            )

        # Every declared output must be populated by the output mapping.
        if isinstance(output_mapping, dict):
            for name in outputs:
                if name not in output_mapping:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E503",
                        f"Mandatory flow output {name!r} is not populated by output_mapping.",
                        parts + ["outputs", name],
                    )

        # 2.3.3 rule 2: a mapping may only reference state that exists.
        available: set[str] = set(inputs)
        step_ids = {
            step.get("id")
            for step in steps
            if isinstance(step, dict) and isinstance(step.get("id"), str)
        }

        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_parts = parts + ["steps", index]
            step_id = step.get("id")

            mapping = step.get("mapping") if isinstance(step.get("mapping"), dict) else {}
            for parameter, path in mapping.items():
                if not isinstance(path, str):
                    continue
                root_variable = path.split(".", 1)[0]
                if root_variable not in available:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E502",
                        f"Mapping references {root_variable!r}, which is not defined in inputs "
                        f"or in the output_map of an earlier step.",
                        step_parts + ["mapping", parameter],
                    )

            output_map = step.get("output_map") if isinstance(step.get("output_map"), dict) else {}
            for variable in output_map:
                if isinstance(variable, str):
                    available.add(variable)

            self._check_condition(doc, step, step_parts, available)
            self._check_error_handling(doc, step, step_parts, step_ids)

    def _check_condition(
        self,
        doc: Document,
        step: dict[str, Any],
        step_parts: list[Any],
        available: set[str],
    ) -> None:
        condition = step.get("condition")
        if condition is None:
            return
        if not isinstance(condition, str):
            return
        try:
            variables = parse_condition(condition)
        except ConditionSyntaxError as error:
            self._diag(
                doc,
                "semantic",
                "error",
                "SDL-E504",
                f"Invalid condition expression: {error.message}",
                step_parts + ["condition"],
            )
            return
        for name, _, _ in variables:
            root_variable = name.split(".", 1)[0]
            if root_variable not in available:
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E502",
                    f"Condition references {root_variable!r}, which is not defined in inputs "
                    f"or in the output_map of an earlier step.",
                    step_parts + ["condition"],
                )

    def _check_error_handling(
        self,
        doc: Document,
        step: dict[str, Any],
        step_parts: list[Any],
        step_ids: set[Any],
    ) -> None:
        on_error = step.get("on_error")
        retry = step.get("retry")

        if on_error is None:
            if retry is not None:
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E505",
                    "A retry policy requires on_error: retry.",
                    step_parts + ["retry"],
                )
            return

        if not isinstance(on_error, str):
            self._diag(
                doc,
                "semantic",
                "error",
                "SDL-E506",
                "on_error must be a string.",
                step_parts + ["on_error"],
            )
            return

        if on_error == "retry":
            if not isinstance(retry, dict):
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E505",
                    "on_error: retry requires a retry policy.",
                    step_parts + ["on_error"],
                )
                return
            attempts = retry.get("attempts")
            if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E505",
                    "retry.attempts must be an integer of at least 1.",
                    step_parts + ["retry", "attempts"],
                )
            return

        if on_error.startswith("goto "):
            target = on_error[5:].strip()
            if target not in step_ids:
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E507",
                    f"on_error: goto references an unknown step {target!r}.",
                    step_parts + ["on_error"],
                )
            return

        if on_error not in ("fail", "ignore"):
            self._diag(
                doc,
                "semantic",
                "error",
                "SDL-E506",
                f"Unknown error handling strategy {on_error!r}.",
                step_parts + ["on_error"],
            )

    # -- bindings (spec section 6.2) ----------------------------------------

    def _check_bindings(self) -> None:
        implementations: dict[str, Symbol] = {}
        for doc in self.documents.values():
            if doc.kind != "implementation":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            name = root.get("id")
            if not isinstance(name, str):
                continue
            symbol = Symbol(name, "implementation", self.project_scope, doc, ["implementation"], data=root)
            implementations[name] = symbol

        for doc in self.documents.values():
            if doc.kind != "project":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            bindings = root.get("bindings")
            if not isinstance(bindings, list):
                continue

            seen: set[tuple[str, str]] = set()
            for index, binding in enumerate(bindings):
                if not isinstance(binding, dict):
                    continue
                interface = binding.get("interface")
                version = binding.get("version")
                implementation = binding.get("implementation")
                if not isinstance(interface, str) or not isinstance(implementation, str):
                    continue

                key = (interface, version if isinstance(version, str) else "")
                if key in seen:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E603",
                        f"Binding for interface {interface!r} is not exclusive.",
                        ["project", "bindings", index],
                    )
                seen.add(key)

                if interface not in self.project_scope.symbols:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E603",
                        f"Binding references unknown interface {interface!r}.",
                        ["project", "bindings", index, "interface"],
                    )

                target = implementations.get(implementation)
                if target is None:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E603",
                        f"Binding references unknown implementation {implementation!r}.",
                        ["project", "bindings", index, "implementation"],
                    )
                    continue

                implemented = target.data.get("implements") if target.data else None
                if not isinstance(implemented, list):
                    continue
                names = {
                    item.get("interface")
                    for item in implemented
                    if isinstance(item, dict)
                }
                if interface not in names:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E604",
                        f"Implementation {implementation!r} does not implement interface {interface!r}.",
                        ["project", "bindings", index, "implementation"],
                    )

    # -- calls and bindings (spec section 6.2, rule three) ------------------

    def _check_call_bindings(self) -> None:
        """Every interface a flow calls must be bound.

        Specification section 6.2, rule three: when a module calls a method
        of an interface, the runtime and the code generator use the bindings
        table to determine which concrete code to execute. A call to an
        interface that the project does not bind cannot be resolved at all.

        A call to a module function needs no binding: the module is the code.
        """
        if not any(doc.kind == "project" for doc in self.documents.values()):
            # The bindings live in the project document, so without one there
            # is nothing to check against.
            return

        bound = self._bound_interfaces()
        for doc in self.documents.values():
            if doc.kind != "flow":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            steps = root.get("steps") if isinstance(root.get("steps"), list) else []
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                call = step.get("call")
                if not isinstance(call, str) or "::" not in call:
                    continue
                owner = call.split("::", 1)[0]

                # A module is the code itself, so it needs no binding.
                if owner in self.module_scopes:
                    continue

                symbol = self.project_scope.symbols.get(owner)
                if symbol is None or symbol.kind != "interface":
                    # An unknown owner is reported by the reference rules.
                    continue

                if owner in bound:
                    continue

                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E603",
                    f"The step {step.get('id')!r} calls the interface {owner!r}, but the "
                    f"project binds no implementation for it.",
                    ["flow", "steps", index, "call"],
                )

    def _bound_interfaces(self) -> set[str]:
        """The interfaces the project binds, in every build."""
        bound: set[str] = set()
        for doc in self.documents.values():
            if doc.kind != "project":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            for binding in self._bindings_of(root.get("bindings")):
                bound.add(binding)
            builds = root.get("builds")
            if not isinstance(builds, list):
                continue
            for build in builds:
                if not isinstance(build, dict):
                    continue
                for binding in self._bindings_of(build.get("bindings_override")):
                    bound.add(binding)
        return bound

    @staticmethod
    def _bindings_of(value: Any) -> list[str]:
        """The interfaces of a list of bindings."""
        names: list[str] = []
        if not isinstance(value, list):
            return names
        for binding in value:
            if not isinstance(binding, dict):
                continue
            interface = binding.get("interface")
            if isinstance(interface, str):
                names.append(interface)
        return names

    # -- backend (spec section 7) -------------------------------------------

    #: The languages a back end of the toolchain can host.
    HOSTED_LANGUAGES: dict[str, frozenset[str]] = {
        "python": frozenset({"python"}),
        "nodejs": frozenset({"typescript", "javascript"}),
    }

    def _check_backend(self) -> None:
        """The target of a build must be able to host the implementations.

        Specification section 7.2: the target must be compatible with the
        languages of all the implementations the build uses. The toolchain
        only knows the languages a back end it implements can host, so the
        rule is checked for those back ends. A target it does not implement
        is refused by the build, not by the validator: the specification is
        independent of the languages the toolchain happens to speak.
        """
        for doc in self.documents.values():
            if doc.kind != "project":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            self._check_backend_target(doc, root.get("backend"), ["project", "backend"])
            builds = root.get("builds")
            if not isinstance(builds, list):
                continue
            for index, build in enumerate(builds):
                if not isinstance(build, dict):
                    continue
                self._check_backend_target(doc, build, ["project", "builds", index])

    def _check_backend_target(
        self,
        doc: Document,
        config: Any,
        parts: list[Any],
    ) -> None:
        if not isinstance(config, dict):
            return
        target = config.get("target")
        if not isinstance(target, str):
            return
        hosted = self.HOSTED_LANGUAGES.get(target)
        if hosted is None:
            return
        languages = self._implementation_languages()
        for implementation in self._used_implementations(config):
            language = languages.get(implementation)
            if language is None or language in hosted:
                continue
            self._diag(
                doc,
                "semantic",
                "error",
                "SDL-E606",
                f"The back end {target!r} cannot host the implementation "
                f"{implementation!r}, which is written in {language!r}.",
                parts + ["target"],
            )

    def _implementation_languages(self) -> dict[str, str]:
        """The language of every implementation of the project."""
        languages: dict[str, str] = {}
        for doc in self.documents.values():
            if doc.kind != "implementation":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            name = root.get("id")
            language = root.get("language")
            if isinstance(name, str) and isinstance(language, str):
                languages[name] = language
        return languages

    def _used_implementations(self, config: dict[str, Any]) -> list[str]:
        """The implementations a build uses."""
        used: list[str] = []
        for doc in self.documents.values():
            if doc.kind != "project":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            bindings = root.get("bindings")
            groups = [bindings]
            overrides = config.get("bindings_override")
            if isinstance(overrides, list):
                groups.append(overrides)
            for group in groups:
                if not isinstance(group, list):
                    continue
                for binding in group:
                    if not isinstance(binding, dict):
                        continue
                    name = binding.get("implementation")
                    if isinstance(name, str) and name not in used:
                        used.append(name)
        return used


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def analyze(doc: Document, report: Report, schema: dict[str, Any]) -> ProjectContext:
    context = ProjectContext(doc, report, schema)
    return context
