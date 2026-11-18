"""Layer 3: SDL YAML to AST.

The parser sits on top of the YAML subset of layer 0, so it inherits the
subset rules for free: no anchors, no aliases, no merge keys, no flow style
collections, exactly one document per file.

The parser does not validate. It reads a document that has already passed the
schema and the semantic layers and turns it into an AST that keeps the
location of every element.
"""

from __future__ import annotations

from typing import Any

from sdl.parser.ast import (
    ASTBackend,
    ASTBinding,
    ASTBuild,
    ASTClass,
    ASTConstraints,
    ASTField,
    ASTFlow,
    ASTFlowStep,
    ASTForbiddenImport,
    ASTImport,
    ASTImplementation,
    ASTInterface,
    ASTInterfaceRef,
    ASTMethod,
    ASTMigration,
    ASTModule,
    ASTNode,
    ASTPatch,
    ASTPolicy,
    ASTProject,
    ASTProposal,
    ASTRetry,
    ASTType,
    ASTTypes,
)
from sdl.yaml.subset import ParsedDocument, SubsetError, location, node_at, parse_text


class SDLParserError(Exception):
    """A document that cannot be turned into an AST."""

    def __init__(self, message: str, file: str | None = None, line: int = 1, column: int = 1):
        super().__init__(message)
        self.message = message
        self.file = file
        self.line = line
        self.column = column


class SDLYamlParser:
    """Parses a single SDL document into an AST node."""

    def __init__(self, filename: str):
        self.filename = filename

    # -- entry point ---------------------------------------------------------

    def parse(self, content: str) -> ASTNode:
        """Parse SDL YAML text into an AST node."""
        try:
            parsed = parse_text(content)
        except SubsetError as error:
            raise SDLParserError(error.message, self.filename, error.line, error.column) from error

        data = parsed.data
        if not isinstance(data, dict):
            raise SDLParserError("Document must be a mapping.", self.filename)

        kind = data.get("kind")
        if not isinstance(kind, str):
            raise SDLParserError("Missing required field 'kind'.", self.filename)

        builder = {
            "project": self._parse_project,
            "module": self._parse_module,
            "interface": self._parse_interface,
            "types": self._parse_types,
            "flow": self._parse_flow,
            "implementation": self._parse_implementation,
            "proposal": self._parse_proposal,
        }.get(kind)

        if builder is None:
            raise SDLParserError(f"Unknown kind {kind!r}.", self.filename)

        root = data.get(kind)
        if root is None:
            raise SDLParserError(f"Missing root key {kind!r} for kind {kind!r}.", self.filename)

        node = builder(root, parsed)
        return node

    # -- helpers -------------------------------------------------------------

    def _loc(self, parsed: ParsedDocument, parts: list[Any]) -> tuple[int | None, int | None]:
        node = node_at(parsed.root, parts)
        if node is None:
            return None, None
        line, column = location(node)
        return line, column

    def _place(self, node: ASTNode, parsed: ParsedDocument, parts: list[Any]) -> ASTNode:
        line, column = self._loc(parsed, parts)
        node.file = self.filename
        node.line = line
        node.column = column
        return node

    @staticmethod
    def _imports(value: Any, parsed: ParsedDocument, base: list[Any]) -> list[ASTImport]:
        if not isinstance(value, list):
            return []
        imports: list[ASTImport] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            module = item.get("module")
            package = item.get("package")
            if not any(isinstance(candidate, str) for candidate in (path, module, package)):
                continue
            imports.append(
                ASTImport(
                    path=path if isinstance(path, str) else "",
                    module=module if isinstance(module, str) else "",
                    package=package if isinstance(package, str) else "",
                )
            )
        return imports

    # -- document kinds ------------------------------------------------------

    def _parse_project(self, root: Any, parsed: ParsedDocument) -> ASTProject:
        if not isinstance(root, dict):
            raise SDLParserError("project must be a mapping.", self.filename)

        node = ASTProject(
            id=str(root.get("id", "unknown")),
            version=str(root.get("version", "0.0.0")),
            imports=self._imports(root.get("imports"), parsed, ["project", "imports"]),
            types=self._type_list(root.get("types"), parsed, ["project", "types"]),
            interfaces=self._interface_list(root.get("interfaces"), parsed, ["project", "interfaces"]),
            bindings=self._bindings(root.get("bindings"), parsed, ["project", "bindings"]),
            backend=self._backend(root.get("backend"), parsed, ["project", "backend"]),
            builds=self._builds(root.get("builds"), parsed, ["project", "builds"]),
            constraints=self._constraints(root.get("constraints"), parsed, ["project", "constraints"]),
            policy=self._policy(root.get("policy"), parsed, ["project", "policy"]),
        )
        return self._place(node, parsed, ["project"])

    def _parse_module(self, root: Any, parsed: ParsedDocument) -> ASTModule:
        if not isinstance(root, dict):
            raise SDLParserError("module must be a mapping.", self.filename)

        node = ASTModule(
            id=str(root.get("id", "unknown")),
            version=str(root.get("version", "0.0.0")),
            imports=self._imports(root.get("imports"), parsed, ["module", "imports"]),
            types=self._type_list(root.get("types"), parsed, ["module", "types"]),
            interfaces=self._interface_list(root.get("interfaces"), parsed, ["module", "interfaces"]),
            classes=self._classes(root.get("classes"), parsed, ["module", "classes"]),
            functions=self._methods(root.get("functions"), parsed, ["module", "functions"]),
            constraints=self._constraints(root.get("constraints"), parsed, ["module", "constraints"]),
        )
        return self._place(node, parsed, ["module"])

    def _parse_types(self, root: Any, parsed: ParsedDocument) -> ASTTypes:
        """A types document carries a list of types and nothing else."""
        node = ASTTypes(
            id="types",
            version="0.0.0",
            types=self._type_list(root, parsed, ["types"]),
        )
        return self._place(node, parsed, ["types"])

    def _parse_interface(self, root: Any, parsed: ParsedDocument) -> ASTInterface:
        if not isinstance(root, dict):
            raise SDLParserError("interface must be a mapping.", self.filename)

        node = ASTInterface(
            id=str(root.get("id", "unknown")),
            version=str(root.get("version", "0.0.0")),
            imports=self._imports(root.get("imports"), parsed, ["interface", "imports"]),
            invariants=[str(item) for item in (root.get("invariants") or []) if isinstance(item, str)],
            methods=self._methods(root.get("methods"), parsed, ["interface", "methods"], callable=True),
        )
        return self._place(node, parsed, ["interface"])

    def _parse_flow(self, root: Any, parsed: ParsedDocument) -> ASTFlow:
        if not isinstance(root, dict):
            raise SDLParserError("flow must be a mapping.", self.filename)

        steps: list[ASTFlowStep] = []
        raw_steps = root.get("steps")
        if isinstance(raw_steps, list):
            for index, item in enumerate(raw_steps):
                if not isinstance(item, dict):
                    continue
                step = ASTFlowStep(
                    id=str(item.get("id", "unknown")),
                    call=str(item.get("call", "")),
                    mapping=self._string_map(item.get("mapping")),
                    output_map=self._string_map(item.get("output_map")),
                    condition=item.get("condition") if isinstance(item.get("condition"), str) else None,
                    on_error=item.get("on_error") if isinstance(item.get("on_error"), str) else None,
                    retry=self._retry(item.get("retry"), parsed, ["flow", "steps", index, "retry"]),
                )
                self._place(step, parsed, ["flow", "steps", index])
                steps.append(step)

        node = ASTFlow(
            id=str(root.get("id", "unknown")),
            version=str(root.get("version", "0.0.0")),
            imports=self._imports(root.get("imports"), parsed, ["flow", "imports"]),
            invariants=[str(item) for item in (root.get("invariants") or []) if isinstance(item, str)],
            inputs=self._string_map(root.get("inputs")),
            steps=steps,
            outputs=self._string_map(root.get("outputs")),
            output_mapping=self._string_map(root.get("output_mapping")),
        )
        return self._place(node, parsed, ["flow"])

    def _parse_implementation(self, root: Any, parsed: ParsedDocument) -> ASTImplementation:
        if not isinstance(root, dict):
            raise SDLParserError("implementation must be a mapping.", self.filename)

        implements: list[ASTInterfaceRef] = []
        raw_implements = root.get("implements")
        if isinstance(raw_implements, list):
            for item in raw_implements:
                if not isinstance(item, dict):
                    continue
                name = item.get("interface")
                if not isinstance(name, str):
                    continue
                implements.append(
                    ASTInterfaceRef(
                        interface=name,
                        version=item.get("version") if isinstance(item.get("version"), str) else None,
                    )
                )

        source = root.get("source")
        source_file = None
        source_symbol = None
        if isinstance(source, dict):
            if isinstance(source.get("file"), str):
                source_file = source["file"]
            if isinstance(source.get("symbol"), str):
                source_symbol = source["symbol"]

        node = ASTImplementation(
            id=str(root.get("id", "unknown")),
            version=str(root.get("version", "0.0.0")),
            implements=implements,
            language=str(root.get("language", "")),
            source_file=source_file,
            source_symbol=source_symbol,
        )
        return self._place(node, parsed, ["implementation"])

    def _parse_proposal(self, root: Any, parsed: ParsedDocument) -> ASTProposal:
        if not isinstance(root, dict):
            raise SDLParserError("proposal must be a mapping.", self.filename)

        patches: list[ASTPatch] = []
        raw_patches = root.get("patches")
        if isinstance(raw_patches, list):
            for index, item in enumerate(raw_patches):
                if not isinstance(item, dict):
                    continue
                patch = ASTPatch(
                    target=str(item.get("target", "")),
                    action=str(item.get("action", "replace")),
                    value=item.get("value"),
                )
                self._place(patch, parsed, ["proposal", "patches", index])
                patches.append(patch)

        node = ASTProposal(
            id=str(root.get("id", "unknown")),
            target_version=str(root.get("target_version", "0.0.0")),
            author=str(root.get("author", "unknown")),
            rationale=str(root.get("rationale", "")),
            patches=patches,
            migration=self._migration(root.get("migration"), parsed),
        )
        return self._place(node, parsed, ["proposal"])

    def _migration(self, raw: Any, parsed: ParsedDocument) -> list[ASTMigration]:
        """The migration plan of a proposal. Specification section 4.3.1."""
        entries: list[ASTMigration] = []
        if not isinstance(raw, list):
            return entries
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            documents = item.get("documents")
            entry = ASTMigration(
                type=str(item.get("type", "")),
                documents=[str(name) for name in documents] if isinstance(documents, list) else [],
            )
            self._place(entry, parsed, ["proposal", "migration", index])
            entries.append(entry)
        return entries

    # -- fragments -----------------------------------------------------------

    def _type_list(self, value: Any, parsed: ParsedDocument, base: list[Any]) -> list[ASTType]:
        """Types appear either as a list or as a mapping keyed by type id."""
        types: list[ASTType] = []

        if isinstance(value, list):
            for index, item in enumerate(value):
                if not isinstance(item, dict):
                    continue
                types.append(self._type(item, str(item.get("id", "unknown")), parsed, base + [index]))
            return types

        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(item, dict):
                    continue
                types.append(self._type(item, str(key), parsed, base + [key]))
        return types

    def _type(self, declaration: dict[str, Any], name: str, parsed: ParsedDocument, base: list[Any]) -> ASTType:
        identifier = declaration.get("id")
        if not isinstance(identifier, str):
            identifier = name

        fields: list[ASTField] = []
        raw_fields = declaration.get("fields")
        if isinstance(raw_fields, dict):
            for field_name, field_type in raw_fields.items():
                if not isinstance(field_type, str):
                    continue
                fields.append(ASTField(name=str(field_name), type_expr=field_type))

        enum_values = [
            str(item)
            for item in (declaration.get("enum") or [])
            if isinstance(item, str)
        ]

        if "enum" in declaration:
            kind = "enum"
        elif "type" in declaration:
            kind = "alias"
        else:
            kind = "compound"

        node = ASTType(
            id=identifier,
            version=str(declaration.get("version", "0.0.0")),
            kind=kind,
            fields=fields,
            type_expr=declaration.get("type") if isinstance(declaration.get("type"), str) else None,
            enum_values=enum_values,
            constraints=[str(item) for item in (declaration.get("constraints") or []) if isinstance(item, str)],
        )
        return self._place(node, parsed, base)

    def _interface_list(self, value: Any, parsed: ParsedDocument, base: list[Any]) -> list[ASTInterface]:
        interfaces: list[ASTInterface] = []
        if not isinstance(value, list):
            return interfaces
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            interfaces.append(self._interface(item, parsed, base + [index]))
        return interfaces

    def _interface(self, declaration: dict[str, Any], parsed: ParsedDocument, base: list[Any]) -> ASTInterface:
        node = ASTInterface(
            id=str(declaration.get("id", "unknown")),
            version=str(declaration.get("version", "0.0.0")),
            imports=self._imports(declaration.get("imports"), parsed, base + ["imports"]),
            invariants=[str(item) for item in (declaration.get("invariants") or []) if isinstance(item, str)],
            methods=self._methods(declaration.get("methods"), parsed, base + ["methods"], callable=True),
        )
        return self._place(node, parsed, base)

    def _methods(
        self,
        value: Any,
        parsed: ParsedDocument,
        base: list[Any],
        callable: bool = False,
    ) -> list[ASTMethod]:
        methods: list[ASTMethod] = []
        if not isinstance(value, list):
            return methods
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            inputs = item.get("inputs")
            if not isinstance(inputs, dict):
                inputs = item.get("input")
            output = item.get("outputs")
            if isinstance(output, dict):
                output = output.get("type")
            if not isinstance(output, str):
                output = item.get("output")
                if isinstance(output, dict):
                    output = output.get("type")
            method = ASTMethod(
                id=str(item.get("id", "unknown")),
                version=str(item.get("version", "0.0.0")),
                inputs=self._string_map(inputs),
                output=output if isinstance(output, str) else None,
                invariants=[str(x) for x in (item.get("invariants") or []) if isinstance(x, str)],
            )
            self._place(method, parsed, base + [index])
            methods.append(method)
        return methods

    def _classes(self, value: Any, parsed: ParsedDocument, base: list[Any]) -> list[ASTClass]:
        classes: list[ASTClass] = []
        if not isinstance(value, list):
            return classes
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            node = ASTClass(
                id=str(item.get("id", "unknown")),
                properties=self._string_map(item.get("properties")),
            )
            self._place(node, parsed, base + [index])
            classes.append(node)
        return classes

    def _bindings(self, value: Any, parsed: ParsedDocument, base: list[Any]) -> list[ASTBinding]:
        bindings: list[ASTBinding] = []
        if not isinstance(value, list):
            return bindings
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            node = ASTBinding(
                interface=str(item.get("interface", "unknown")),
                version=item.get("version") if isinstance(item.get("version"), str) else None,
                implementation=str(item.get("implementation", "unknown")),
            )
            self._place(node, parsed, base + [index])
            bindings.append(node)
        return bindings

    def _backend(self, value: Any, parsed: ParsedDocument, base: list[Any]) -> ASTBackend | None:
        if not isinstance(value, dict):
            return None
        options = value.get("options")
        node = ASTBackend(
            target=str(value.get("target", "python")),
            mode=str(value.get("mode", "codegen")),
            options=dict(options) if isinstance(options, dict) else {},
        )
        return self._place(node, parsed, base)

    def _builds(self, value: Any, parsed: ParsedDocument, base: list[Any]) -> list[ASTBuild]:
        builds: list[ASTBuild] = []
        if not isinstance(value, list):
            return builds
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            node = ASTBuild(
                id=str(item.get("id", "unknown")),
                target=str(item.get("target", "python")),
                mode=str(item.get("mode", "codegen")),
                bindings_override=self._bindings(
                    item.get("bindings_override"), parsed, base + [index, "bindings_override"]
                ),
            )
            self._place(node, parsed, base + [index])
            builds.append(node)
        return builds

    def _constraints(self, value: Any, parsed: ParsedDocument, base: list[Any]) -> ASTConstraints | None:
        if not isinstance(value, dict):
            return None
        forbidden: list[ASTForbiddenImport] = []
        raw = value.get("forbidden_imports")
        if isinstance(raw, list):
            for index, item in enumerate(raw):
                if not isinstance(item, dict):
                    continue
                deny = item.get("deny")
                node = ASTForbiddenImport(
                    from_module=str(item.get("from", "unknown")),
                    deny=[str(x) for x in deny if isinstance(x, str)] if isinstance(deny, list) else [],
                    reason=str(item.get("reason", "")),
                )
                self._place(node, parsed, base + ["forbidden_imports", index])
                forbidden.append(node)
        node = ASTConstraints(forbidden_imports=forbidden)
        return self._place(node, parsed, base)

    def _policy(self, value: Any, parsed: ParsedDocument, base: list[Any]) -> ASTPolicy | None:
        if not isinstance(value, dict):
            return None
        node = ASTPolicy(
            disallow_breaking_changes=bool(value.get("disallow_breaking_changes", False)),
            require_migration_for_type_change=bool(value.get("require_migration_for_type_change", False)),
            forbidden_id_changes=bool(value.get("forbidden_id_changes", False)),
        )
        return self._place(node, parsed, base)

    def _retry(self, value: Any, parsed: ParsedDocument, base: list[Any]) -> ASTRetry | None:
        if not isinstance(value, dict):
            return None
        attempts = value.get("attempts")
        node = ASTRetry(
            attempts=attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 1,
            backoff=value.get("backoff") if isinstance(value.get("backoff"), str) else None,
            initial_interval=(
                value.get("initial_interval") if isinstance(value.get("initial_interval"), str) else None
            ),
            max_interval=value.get("max_interval") if isinstance(value.get("max_interval"), str) else None,
        )
        return self._place(node, parsed, base)

    @staticmethod
    def _string_map(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            str(key): item
            for key, item in value.items()
            if isinstance(item, str)
        }
