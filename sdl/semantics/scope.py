"""Semantic analysis for SDL Core 0.2.

Covers scopes, duplicate IDs, imports/visibility, type resolution, alias
cycles, generic arity, Unit restrictions, direct class recursion and inference
warnings. Flow semantics, interface compatibility and code generation are out
of scope for 0.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sdl.diagnostics import Report, json_pointer
from sdl.schema.envelope import (
    SNAKE_ID,
    normalize_import_path,
    validate_json_schema,
    validate_schema,
)
from sdl.types import expressions as sdl_types
from sdl.yaml.subset import ParsedDocument, SubsetError, location, node_at, parse_file


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
    methods: list[tuple[dict[str, Any], list[Any]]] = field(default_factory=list)
    properties: list[tuple[sdl_types.TypeExpr, list[Any]]] = field(default_factory=list)


@dataclass
class Scope:
    name: str
    symbols: dict[str, Symbol] = field(default_factory=dict)


@dataclass
class ModuleInfo:
    id: str
    doc: Document
    scope: Scope
    all_ids: dict[str, list[Any]] = field(default_factory=dict)
    imports: set[str] = field(default_factory=set)


class ProjectContext:
    def __init__(self, start: Document, report: Report, schema: dict[str, Any]):
        self.start = start
        self.report = report
        self.schema = schema
        self.base_dir = start.path.parent
        self.documents: dict[Path, Document] = {start.path.resolve(): start}
        self.project_scope = Scope("project")
        self.modules: dict[str, ModuleInfo] = {}
        self.module_scopes: dict[str, Scope] = {}
        self.module_imports: dict[str, set[str]] = {}

        if start.kind == "project":
            self._load_project_imports()
        self._build_project_scope()
        self._build_module_scopes()
        self._check_shadowing()
        self._check_alias_cycles()
        self._check_class_recursion()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_project_imports(self) -> None:
        root = self.start.root_value
        if not isinstance(root, dict):
            return
        imports = root.get("imports")
        if not isinstance(imports, list):
            return

        for index, item in enumerate(imports):
            if not isinstance(item, dict) or "path" not in item:
                continue
            normalized = normalize_import_path(item["path"])
            if normalized is None:
                continue
            target = (self.base_dir / normalized).resolve()
            try:
                target.relative_to(self.base_dir.resolve())
            except ValueError:
                continue
            if target in self.documents:
                continue
            if not target.exists():
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

            if kind == "project":
                self._diag(
                    self.start,
                    "semantic",
                    "error",
                    "SDL-E300",
                    "Project imports must not reference a project document.",
                    ["project", "imports", index, "path"],
                )
                continue

            doc_id = None
            if kind in ("project", "module", "interface"):
                root_value = parsed.data.get(kind)
                if isinstance(root_value, dict) and isinstance(root_value.get("id"), str):
                    doc_id = root_value["id"]
            self.documents[target] = Document(target, file_rel, parsed, kind, doc_id)

    # ------------------------------------------------------------------
    # Scope construction
    # ------------------------------------------------------------------

    def _build_project_scope(self) -> None:
        for doc in self.documents.values():
            if doc.kind == "project":
                root = doc.root_value
                if not isinstance(root, dict):
                    continue
                self._add_types(doc, root.get("types"), ["project", "types"])
                self._add_interfaces(doc, root.get("interfaces"), ["project", "interfaces"])
            elif doc.kind == "types":
                root = doc.root_value
                if isinstance(root, list):
                    self._add_types(doc, root, ["types"])
            elif doc.kind == "interface":
                root = doc.root_value
                if isinstance(root, dict):
                    self._add_interface(doc, root, ["interface"])

    def _build_module_scopes(self) -> None:
        for doc in self.documents.values():
            if doc.kind != "module":
                continue
            root = doc.root_value
            if not isinstance(root, dict):
                continue
            module_id = root.get("id")
            if not isinstance(module_id, str) or not SNAKE_ID.match(module_id):
                continue
            if module_id in self.modules:
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
            info = ModuleInfo(module_id, doc, scope)
            self.modules[module_id] = info
            self.module_scopes[module_id] = scope

            self._add_types(doc, root.get("types"), ["module", "types"], info)
            self._add_interfaces(doc, root.get("interfaces"), ["module", "interfaces"], info)
            self._add_classes(doc, root.get("classes"), ["module", "classes"], info)
            self._add_functions(doc, root.get("functions"), ["module", "functions"], info)

            imports = root.get("imports")
            if isinstance(imports, list):
                for item in imports:
                    if isinstance(item, dict) and isinstance(item.get("module"), str):
                        info.imports.add(item["module"])
            self.module_imports[module_id] = info.imports

    def _add_types(
        self,
        doc: Document,
        value: Any,
        prefix: list[Any],
        module: ModuleInfo | None = None,
    ) -> None:
        if not isinstance(value, list):
            return
        for index, declaration in enumerate(value):
            if not isinstance(declaration, dict):
                continue
            name = declaration.get("id")
            if not isinstance(name, str):
                continue
            parts = prefix + [index]
            if "type" in declaration:
                symbol_kind = "alias"
                expression = None
                if isinstance(declaration["type"], str):
                    try:
                        expression = sdl_types.parse(declaration["type"])
                    except sdl_types.TypeSyntaxError:
                        expression = None
                symbol = Symbol(name, symbol_kind, self.project_scope, doc, parts, expr=expression)
            elif "enum" in declaration:
                symbol = Symbol(name, "enum", self.project_scope, doc, parts)
                self._check_enum_values(doc, declaration, parts)
            else:
                continue
            if module is None:
                self._add_project_symbol(symbol)
            else:
                symbol.scope = module.scope
                self._add_module_symbol(module, symbol)

    def _add_interfaces(
        self,
        doc: Document,
        value: Any,
        prefix: list[Any],
        module: ModuleInfo | None = None,
    ) -> None:
        if not isinstance(value, list):
            return
        for index, interface in enumerate(value):
            if isinstance(interface, dict):
                self._add_interface(doc, interface, prefix + [index], module)

    def _add_interface(
        self,
        doc: Document,
        interface: dict[str, Any],
        parts: list[Any],
        module: ModuleInfo | None = None,
    ) -> None:
        name = interface.get("id")
        if not isinstance(name, str):
            return
        methods: list[tuple[dict[str, Any], list[Any]]] = []
        seen: dict[str, list[Any]] = {}
        raw_methods = interface.get("methods")
        if isinstance(raw_methods, list):
            for index, method in enumerate(raw_methods):
                method_parts = parts + ["methods", index]
                if not isinstance(method, dict):
                    continue
                method_id = method.get("id")
                if isinstance(method_id, str):
                    if method_id in seen:
                        self._diag(
                            doc,
                            "semantic",
                            "error",
                            "SDL-E211",
                            f"Duplicate method ID {method_id!r}.",
                            method_parts + ["id"],
                        )
                    else:
                        seen[method_id] = method_parts
                methods.append((method, method_parts))
        symbol = Symbol(
            name,
            "interface",
            self.project_scope,
            doc,
            parts,
            data=interface,
            version=interface.get("version") if isinstance(interface.get("version"), str) else None,
            methods=methods,
        )
        if module is None:
            self._add_project_symbol(symbol)
        else:
            symbol.scope = module.scope
            self._add_module_symbol(module, symbol)

    def _add_classes(
        self,
        doc: Document,
        value: Any,
        prefix: list[Any],
        module: ModuleInfo,
    ) -> None:
        if not isinstance(value, list):
            return
        for index, class_decl in enumerate(value):
            if not isinstance(class_decl, dict):
                continue
            name = class_decl.get("id")
            if not isinstance(name, str):
                continue
            parts = prefix + [index]
            properties: list[tuple[sdl_types.TypeExpr, list[Any]]] = []
            raw_properties = class_decl.get("properties")
            if isinstance(raw_properties, dict):
                for property_name, value in raw_properties.items():
                    property_parts = parts + ["properties", property_name]
                    if isinstance(value, str):
                        try:
                            expression = sdl_types.parse(value)
                        except sdl_types.TypeSyntaxError:
                            continue
                        properties.append((expression, property_parts))
            symbol = Symbol(
                name,
                "class",
                module.scope,
                doc,
                parts,
                data=class_decl,
                properties=properties,
            )
            self._add_module_symbol(module, symbol)

    def _add_functions(
        self,
        doc: Document,
        value: Any,
        prefix: list[Any],
        module: ModuleInfo,
    ) -> None:
        if not isinstance(value, list):
            return
        for index, function in enumerate(value):
            if not isinstance(function, dict):
                continue
            name = function.get("id")
            if not isinstance(name, str):
                continue
            parts = prefix + [index]
            if name in module.all_ids:
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E211",
                    f"Duplicate ID {name!r} in module {module.id!r}.",
                    parts + ["id"],
                )
            else:
                module.all_ids[name] = parts

    def _add_project_symbol(self, symbol: Symbol) -> None:
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
        if symbol.name in self.project_scope.symbols:
            self._diag(
                symbol.doc,
                "semantic",
                "error",
                "SDL-E211",
                f"Duplicate project ID {symbol.name!r}.",
                symbol.parts + ["id"],
            )
            return
        self.project_scope.symbols[symbol.name] = symbol

    def _add_module_symbol(self, module: ModuleInfo, symbol: Symbol) -> None:
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
        if symbol.name in module.all_ids:
            self._diag(
                symbol.doc,
                "semantic",
                "error",
                "SDL-E211",
                f"Duplicate ID {symbol.name!r} in module {module.id!r}.",
                symbol.parts + ["id"],
            )
            return
        module.all_ids[symbol.name] = symbol.parts
        module.scope.symbols[symbol.name] = symbol

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
        for module in self.modules.values():
            for name in module.all_ids:
                if name in self.project_scope.symbols:
                    parts = module.all_ids[name]
                    self._diag(
                        module.doc,
                        "semantic",
                        "error",
                        "SDL-E213",
                        f"Module ID {name!r} shadows a project ID.",
                        parts + ["id"],
                    )

    # ------------------------------------------------------------------
    # Alias cycles and class recursion
    # ------------------------------------------------------------------

    def _all_symbols(self) -> Iterable[Symbol]:
        yield from self.project_scope.symbols.values()
        for scope in self.module_scopes.values():
            yield from scope.symbols.values()

    @staticmethod
    def _names(expression: sdl_types.TypeExpr | None) -> Iterable[sdl_types.TypeName]:
        if expression is None:
            return
        if isinstance(expression, sdl_types.TypeName):
            yield expression
        elif isinstance(expression, sdl_types.TypeGeneric):
            for arg in expression.args:
                yield from ProjectContext._names(arg)
        elif isinstance(expression, sdl_types.TypeUnion):
            for item in expression.items:
                yield from ProjectContext._names(item)

    @staticmethod
    def _direct_names(expression: sdl_types.TypeExpr) -> Iterable[sdl_types.TypeName]:
        if isinstance(expression, sdl_types.TypeName):
            yield expression
        elif isinstance(expression, sdl_types.TypeUnion):
            for item in expression.items:
                yield from ProjectContext._direct_names(item)

    def _check_alias_cycles(self) -> None:
        aliases = [symbol for symbol in self._all_symbols() if symbol.kind == "alias"]
        graph: dict[Symbol, list[Symbol]] = {symbol: [] for symbol in aliases}
        for symbol in aliases:
            for name in self._names(symbol.expr):
                target, _ = self._resolve(name.name, symbol.doc, symbol.scope)
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
        classes = [symbol for symbol in self._all_symbols() if symbol.kind == "class"]
        graph: dict[Symbol, list[Symbol]] = {symbol: [] for symbol in classes}
        for symbol in classes:
            for expression, _ in symbol.properties:
                for name in self._direct_names(expression):
                    target, _ = self._resolve(name.name, symbol.doc, symbol.scope)
                    if target is not None and target.kind == "class":
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
                            cycle_symbol.parts + ["properties"],
                        )
            stack.pop()
            state[symbol] = 2

        for symbol in classes:
            if state.get(symbol, 0) == 0:
                visit(symbol)

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------

    def check_imports(self) -> None:
        for doc in self.documents.values():
            if doc.kind == "project":
                self._check_project_imports(doc)
            elif doc.kind == "module":
                self._check_module_imports(doc)
        self._check_module_cycles()

    def _check_project_imports(self, doc: Document) -> None:
        root = doc.root_value
        if not isinstance(root, dict):
            return
        imports = root.get("imports")
        if not isinstance(imports, list):
            return
        seen: set[str] = set()
        for index, item in enumerate(imports):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            normalized = normalize_import_path(item["path"])
            if normalized is None:
                continue
            key = normalized.casefold()
            parts = ["project", "imports", index, "path"]
            if key in seen:
                self._diag(doc, "semantic", "error", "SDL-E303", "Duplicate import path.", parts)
                continue
            seen.add(key)
            target = (self.base_dir / normalized).resolve()
            try:
                target.relative_to(self.base_dir.resolve())
            except ValueError:
                self._diag(doc, "schema", "error", "SDL-E300", "Import path escapes the project root.", parts)
                continue
            if not target.exists():
                self._diag(doc, "semantic", "error", "SDL-E302", "Imported file does not exist.", parts)
                continue
            imported = self.documents.get(target)
            if imported is not None and imported.kind == "project":
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E300",
                    "Project import must not reference a project document.",
                    parts,
                )

    def _check_module_imports(self, doc: Document) -> None:
        root = doc.root_value
        if not isinstance(root, dict) or not isinstance(doc.id, str):
            return
        imports = root.get("imports")
        if not isinstance(imports, list):
            return
        seen_modules: set[str] = set()
        seen_packages: set[tuple[str, str]] = set()
        for index, item in enumerate(imports):
            if not isinstance(item, dict):
                continue
            parts = ["module", "imports", index]
            module_name = item.get("module")
            if isinstance(module_name, str):
                if module_name == doc.id:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E301",
                        "A module must not import itself.",
                        parts + ["module"],
                    )
                    continue
                if module_name in seen_modules:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E303",
                        f"Duplicate module import {module_name!r}.",
                        parts + ["module"],
                    )
                else:
                    seen_modules.add(module_name)
                    if module_name not in self.modules:
                        self._diag(
                            doc,
                            "semantic",
                            "error",
                            "SDL-E302",
                            f"Unknown module {module_name!r}.",
                            parts + ["module"],
                        )
            package_name = item.get("package")
            if isinstance(package_name, str):
                version = item.get("version") if isinstance(item.get("version"), str) else ""
                key = (package_name, version)
                if key in seen_packages:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E303",
                        f"Duplicate package import {package_name!r}.",
                        parts + ["package"],
                    )
                else:
                    seen_packages.add(key)

    def _check_module_cycles(self) -> None:
        edges: dict[str, list[tuple[str, Document, list[Any]]]] = {}
        for module in self.modules.values():
            root = module.doc.root_value
            if not isinstance(root, dict):
                continue
            imports = root.get("imports")
            if not isinstance(imports, list):
                continue
            for index, item in enumerate(imports):
                if not isinstance(item, dict):
                    continue
                target = item.get("module")
                if isinstance(target, str) and target in self.modules and target != module.id:
                    edges.setdefault(module.id, []).append(
                        (target, module.doc, ["module", "imports", index, "module"])
                    )

        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(module_id: str) -> None:
            state[module_id] = 1
            stack.append(module_id)
            for target, doc, parts in edges.get(module_id, []):
                if state.get(target, 0) == 0:
                    visit(target)
                elif state.get(target) == 1 and target in stack:
                    self._diag(doc, "semantic", "error", "SDL-E301", "Cyclic module import.", parts)
            stack.pop()
            state[module_id] = 2

        for module_id in self.modules:
            if state.get(module_id, 0) == 0:
                visit(module_id)

    # ------------------------------------------------------------------
    # Type checking
    # ------------------------------------------------------------------

    def _resolve(self, name: str, doc: Document, scope: Scope) -> tuple[Symbol | None, str | None]:
        if "::" in name:
            scope_name, type_name = name.split("::", 1)
            if scope_name == "project":
                return self.project_scope.symbols.get(type_name), None
            if doc.kind == "module" and scope_name == doc.id:
                return scope.symbols.get(type_name), None
            if scope_name not in self.modules:
                return None, "unknown"
            if doc.kind != "module" or scope_name not in self.module_imports.get(doc.id or "", set()):
                return None, "not_imported"
            return self.module_scopes[scope_name].symbols.get(type_name), None

        if doc.kind == "module":
            symbol = scope.symbols.get(name)
            if symbol is not None:
                return symbol, None
        return self.project_scope.symbols.get(name), None

    def _alias_builtin(self, symbol: Symbol, seen: set[Symbol] | None = None) -> str | None:
        if symbol.kind != "alias" or symbol.expr is None:
            return None
        if seen is None:
            seen = set()
        if symbol in seen:
            return None
        seen.add(symbol)
        if not isinstance(symbol.expr, sdl_types.TypeName):
            return None
        name = symbol.expr.name
        if name in sdl_types.SIMPLE_BUILTINS:
            return name
        target, _ = self._resolve(name, symbol.doc, symbol.scope)
        if target is None:
            return None
        return self._alias_builtin(target, seen)

    def _check_name(self, name: str, doc: Document, scope: Scope, parts: list[Any], context: str) -> None:
        symbol, reason = self._resolve(name, doc, scope)
        if symbol is None:
            if reason == "not_imported":
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E212",
                    f"Module for type {name!r} is not imported.",
                    parts,
                )
            else:
                self._diag(doc, "semantic", "error", "SDL-E401", f"Unknown type {name!r}.", parts)
            return
        if context == "map_key":
            builtin = self._alias_builtin(symbol)
            if builtin not in ("String", "Int", "UUID"):
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E406",
                    "Map key must be String, Int or UUID.",
                    parts,
                )
            return
        if context not in ("output", "result_ok") and self._alias_builtin(symbol) == "Unit":
            self._diag(doc, "semantic", "error", "SDL-E405", "Unit is not allowed in this position.", parts)

    def _check_map_key(self, expression: sdl_types.TypeExpr, doc: Document, scope: Scope, parts: list[Any]) -> None:
        if isinstance(expression, sdl_types.TypeName):
            name = expression.name
            if name in ("String", "Int", "UUID"):
                return
            if name == "Unit":
                self._diag(doc, "semantic", "error", "SDL-E405", "Unit is not allowed as a map key.", parts)
                return
            if name in sdl_types.SIMPLE_BUILTINS or name in sdl_types.GENERIC_ARITY:
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E406",
                    "Map key must be String, Int or UUID.",
                    parts,
                )
                return
            self._check_name(name, doc, scope, parts, "map_key")
            return
        if isinstance(expression, sdl_types.TypeUnion):
            self._diag(
                doc,
                "semantic",
                "error",
                "SDL-E406",
                "Map key must be String, Int or UUID.",
                parts,
            )
            return
        self._diag(doc, "semantic", "error", "SDL-E406", "Map key must be String, Int or UUID.", parts)

    def check_expression(
        self,
        expression: sdl_types.TypeExpr,
        doc: Document,
        scope: Scope,
        parts: list[Any],
        context: str,
    ) -> None:
        if context == "map_key":
            self._check_map_key(expression, doc, scope, parts)
            return

        if isinstance(expression, sdl_types.TypeUnion):
            child_context = "unit_forbidden" if context in ("output", "result_ok") else context
            for item in expression.items:
                self.check_expression(item, doc, scope, parts, child_context)
            return

        if isinstance(expression, sdl_types.TypeGeneric):
            name = expression.name
            if name in sdl_types.GENERIC_ARITY:
                expected = sdl_types.GENERIC_ARITY[name]
                if len(expression.args) != expected:
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E406",
                        f"{name} expects {expected} type argument(s), got {len(expression.args)}.",
                        parts,
                    )
                if name == "Map":
                    if expression.args:
                        self.check_expression(expression.args[0], doc, scope, parts, "map_key")
                    if len(expression.args) > 1:
                        value_context = "alias" if context == "alias" else "unit_forbidden"
                        self.check_expression(expression.args[1], doc, scope, parts, value_context)
                elif name == "Result":
                    if expression.args:
                        ok_context = "alias" if context == "alias" else "result_ok"
                        self.check_expression(expression.args[0], doc, scope, parts, ok_context)
                    if len(expression.args) > 1:
                        err_context = "alias" if context == "alias" else "unit_forbidden"
                        self.check_expression(expression.args[1], doc, scope, parts, err_context)
                else:
                    arg_context = "alias" if context == "alias" else "unit_forbidden"
                    for argument in expression.args:
                        self.check_expression(argument, doc, scope, parts, arg_context)
                return

            symbol, reason = self._resolve(name, doc, scope)
            if symbol is None:
                if reason == "not_imported":
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E212",
                        f"Module for type {name!r} is not imported.",
                        parts,
                    )
                else:
                    self._diag(doc, "semantic", "error", "SDL-E401", f"Unknown type {name!r}.", parts)
            else:
                self._diag(
                    doc,
                    "semantic",
                    "error",
                    "SDL-E406",
                    "User-defined generic types are not part of 0.2.",
                    parts,
                )
            for argument in expression.args:
                self.check_expression(argument, doc, scope, parts, "unit_forbidden")
            return

        name = expression.name
        if name in sdl_types.SIMPLE_BUILTINS:
            if name == "Unit":
                if context not in ("output", "result_ok"):
                    self._diag(
                        doc,
                        "semantic",
                        "error",
                        "SDL-E405",
                        "Unit is only allowed as output or as Result<Unit, E>.",
                        parts,
                    )
            return
        if name in sdl_types.GENERIC_ARITY:
            self._diag(
                doc,
                "semantic",
                "error",
                "SDL-E406",
                f"{name} requires type arguments.",
                parts,
            )
            return
        self._check_name(name, doc, scope, parts, context)

    def _parse_or_none(self, value: Any) -> sdl_types.TypeExpr | None:
        if not isinstance(value, str):
            return None
        try:
            return sdl_types.parse(value)
        except sdl_types.TypeSyntaxError:
            return None

    def _warn_inference(self, value: Any, doc: Document, parts: list[Any]) -> None:
        if not isinstance(value, dict):
            return
        origin = value.get("origin")
        if origin == "inferred" and value.get("status", "proposed") != "approved":
            self._diag(
                doc,
                "semantic",
                "warning",
                "SDL-W100",
                "Proposed inference must not be used for code generation.",
                parts,
            )
        elif origin == "unresolved":
            self._diag(
                doc,
                "semantic",
                "warning",
                "SDL-W101",
                "Unresolved type must be resolved before code generation.",
                parts,
            )

    def _check_properties(
        self,
        doc: Document,
        scope: Scope,
        value: Any,
        parts: list[Any],
        context: str,
    ) -> None:
        if not isinstance(value, dict):
            return
        for name, type_value in value.items():
            property_parts = parts + [name]
            if isinstance(type_value, dict):
                self._warn_inference(type_value, doc, property_parts)
            else:
                expression = self._parse_or_none(type_value)
                if expression is not None:
                    self.check_expression(expression, doc, scope, property_parts, context)

    def _check_output(self, doc: Document, scope: Scope, value: Any, parts: list[Any]) -> None:
        if not isinstance(value, dict):
            return
        expression = self._parse_or_none(value.get("type"))
        if expression is not None:
            self.check_expression(expression, doc, scope, parts + ["type"], "output")

    def _check_callable(self, doc: Document, scope: Scope, value: Any, parts: list[Any]) -> None:
        if not isinstance(value, dict):
            return
        if "input" in value:
            self._check_properties(doc, scope, value["input"], parts + ["input"], "input")
        if "output" in value:
            self._check_output(doc, scope, value["output"], parts + ["output"])

    def _check_interface(self, doc: Document, scope: Scope, value: Any, parts: list[Any]) -> None:
        if not isinstance(value, dict):
            return
        methods = value.get("methods")
        if not isinstance(methods, list):
            return
        for index, method in enumerate(methods):
            self._check_callable(doc, scope, method, parts + ["methods", index])

    def _check_type_declaration(self, doc: Document, scope: Scope, value: Any, parts: list[Any]) -> None:
        if not isinstance(value, dict):
            return
        if "type" in value and "enum" not in value:
            expression = self._parse_or_none(value["type"])
            if expression is not None:
                self.check_expression(expression, doc, scope, parts + ["type"], "alias")

    def check_document(self, doc: Document) -> None:
        root = doc.root_value
        if root is None:
            return
        if doc.kind == "project" and isinstance(root, dict):
            scope = self.project_scope
            types = root.get("types")
            if isinstance(types, list):
                for index, declaration in enumerate(types):
                    self._check_type_declaration(doc, scope, declaration, ["project", "types", index])
            interfaces = root.get("interfaces")
            if isinstance(interfaces, list):
                for index, interface in enumerate(interfaces):
                    self._check_interface(doc, scope, interface, ["project", "interfaces", index])
        elif doc.kind == "types" and isinstance(root, list):
            scope = self.project_scope
            for index, declaration in enumerate(root):
                self._check_type_declaration(doc, scope, declaration, ["types", index])
        elif doc.kind == "interface" and isinstance(root, dict):
            self._check_interface(doc, self.project_scope, root, ["interface"])
        elif doc.kind == "module" and isinstance(root, dict) and isinstance(doc.id, str):
            scope = self.module_scopes.get(doc.id)
            if scope is None:
                return
            types = root.get("types")
            if isinstance(types, list):
                for index, declaration in enumerate(types):
                    self._check_type_declaration(doc, scope, declaration, ["module", "types", index])
            interfaces = root.get("interfaces")
            if isinstance(interfaces, list):
                for index, interface in enumerate(interfaces):
                    self._check_interface(doc, scope, interface, ["module", "interfaces", index])
            classes = root.get("classes")
            if isinstance(classes, list):
                for index, class_decl in enumerate(classes):
                    if isinstance(class_decl, dict) and "properties" in class_decl:
                        self._check_properties(
                            doc,
                            scope,
                            class_decl["properties"],
                            ["module", "classes", index, "properties"],
                            "property",
                        )
            functions = root.get("functions")
            if isinstance(functions, list):
                for index, function in enumerate(functions):
                    self._check_callable(doc, scope, function, ["module", "functions", index])


def analyze(doc: Document, report: Report, schema: dict[str, Any]) -> ProjectContext:
    context = ProjectContext(doc, report, schema)
    context.check_imports()
    for document in context.documents.values():
        context.check_document(document)
    return context
