"""JSON Schema and shape checks for SDL Core 0.2 documents."""

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator
from yaml.nodes import Node

from sdl.diagnostics import Report, json_pointer
from sdl.types import expressions as sdl_types
from sdl.yaml.subset import ParsedDocument, is_double_quoted, is_string_node, location, node_at

#: Core versions this layer understands.
CORE_VERSIONS = ("0.2", "1.0")

#: Document kinds valid in Core 0.2.
KINDS_0_2 = ("project", "module", "interface", "types")

#: Document kinds valid in Core 1.0. Core 1.0 adds flow, implementation and
#: proposal documents to the Core 0.2 set.
KINDS_1_0 = ("project", "module", "interface", "types", "flow", "implementation", "proposal")

#: Alias kept for the Core 0.2 semantics layer.
KINDS = KINDS_0_2

TOP_FIELDS = {"sdl", "kind"}
PROJECT_FIELDS = {"id", "version", "mode", "imports", "types", "interfaces"}
MODULE_FIELDS = {"id", "mode", "imports", "types", "interfaces", "classes", "functions"}
INTERFACE_FIELDS = {"id", "version", "methods"}
TYPE_DECL_FIELDS = {"id", "type", "enum"}
CLASS_FIELDS = {"id", "properties"}
FUNCTION_FIELDS = {"id", "input", "output"}
OUTPUT_FIELDS = {"type"}
INFERRED_FIELDS = {"origin", "type", "confidence", "status"}
UNRESOLVED_FIELDS = {"origin", "reason"}

SNAKE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
PASCAL_ID = re.compile(r"^[A-Z][A-Za-z0-9]*$")
PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
COMPARATOR = re.compile(r"^(\^|~|>=|<=|>|<|=)?([0-9]+\.[0-9]+\.[0-9]+)$")


def valid_range(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if "," in value or "||" in value:
        return False
    parts = value.split()
    return bool(parts) and all(COMPARATOR.match(part) for part in parts)


def normalize_import_path(value: Any) -> str | None:
    """Return a normalised relative path, or None when the path is invalid."""

    if not isinstance(value, str) or not value:
        return None
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return None
    if not value.endswith(".sdl.yaml"):
        return None
    segments: list[str] = []
    for segment in value.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not segments:
                return None
            segments.pop()
            continue
        segments.append(segment)
    if not segments:
        return None
    return "/".join(segments)


def _node(parsed: ParsedDocument, parts: list[Any]) -> Node | None:
    return node_at(parsed.root, parts)


def _add(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    phase: str,
    code: str,
    message: str,
    parts: list[Any],
    severity: str = "error",
) -> None:
    node = _node(parsed, parts)
    line, column = location(node)
    report.add(phase, severity, code, message, file, line, column, json_pointer(parts))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)


def _check_id(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
    pattern: re.Pattern[str],
    label: str,
) -> None:
    if not isinstance(value, str) or not pattern.match(value):
        _add(report, parsed, file, "schema", "SDL-E210", f"Invalid {label} ID.", parts)


def _check_exact_version(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
    label: str,
) -> None:
    node = _node(parsed, parts)
    if not isinstance(value, str) or not VERSION.match(value):
        _add(
            report,
            parsed,
            file,
            "schema",
            "SDL-E220",
            f"{label} must be MAJOR.MINOR.PATCH.",
            parts,
        )
        return
    if not is_double_quoted(node):
        _add(
            report,
            parsed,
            file,
            "schema",
            "SDL-E220",
            f"{label} must be a double-quoted string.",
            parts,
        )


def _check_mode(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
) -> None:
    if value not in ("structural", "declarative"):
        _add(report, parsed, file, "schema", "SDL-E205", "Invalid mode.", parts)


def _check_object(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
    allowed: set[str],
    required: set[str],
    label: str,
    unknown_code: str = "SDL-E203",
) -> bool:
    if not isinstance(value, dict):
        _add(report, parsed, file, "schema", "SDL-E205", f"{label} must be a mapping.", parts)
        return False
    for key in value:
        if key not in allowed:
            _add(
                report,
                parsed,
                file,
                "schema",
                unknown_code,
                f"Unknown field {key!r} in {label}.",
                parts + [key],
            )
    for key in required:
        if key not in value:
            _add(
                report,
                parsed,
                file,
                "schema",
                "SDL-E204",
                f"Missing required field {key!r} in {label}.",
                parts,
            )
    return True


def _check_type_expression(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
) -> None:
    if not isinstance(value, str):
        _add(report, parsed, file, "schema", "SDL-E205", "Type expression must be a string.", parts)
        return
    try:
        sdl_types.parse(value)
    except sdl_types.TypeSyntaxError as error:
        _add(
            report,
            parsed,
            file,
            "schema",
            "SDL-E400",
            f"Invalid type expression: {error.message}",
            parts,
        )


def _check_type_or_inference(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
    label: str,
) -> None:
    if isinstance(value, str):
        _check_type_expression(report, parsed, file, value, parts)
        return
    if isinstance(value, dict):
        _check_inference(report, parsed, file, value, parts, label)
        return
    _add(
        report,
        parsed,
        file,
        "schema",
        "SDL-E205",
        f"{label} must be a type expression or an inference object.",
        parts,
    )


def _check_inference(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: dict[str, Any],
    parts: list[Any],
    label: str,
) -> None:
    origin = value.get("origin")
    if origin is None:
        _add(report, parsed, file, "schema", "SDL-E407", "Inference object requires origin.", parts)
        return
    if origin not in ("inferred", "unresolved"):
        _add(report, parsed, file, "schema", "SDL-E407", "Invalid inference origin.", parts + ["origin"])
        return

    if origin == "inferred":
        _check_object(
            report,
            parsed,
            file,
            value,
            parts,
            INFERRED_FIELDS,
            {"origin", "type"},
            label,
        )
        if "type" in value:
            if not isinstance(value["type"], str):
                _add(
                    report,
                    parsed,
                    file,
                    "schema",
                    "SDL-E205",
                    "Inferred type must be a type expression string.",
                    parts + ["type"],
                )
            else:
                _check_type_expression(report, parsed, file, value["type"], parts + ["type"])
        if "confidence" in value:
            confidence = value["confidence"]
            if not _is_number(confidence) or not 0.0 <= float(confidence) <= 1.0:
                _add(
                    report,
                    parsed,
                    file,
                    "schema",
                    "SDL-E205",
                    "confidence must be a number between 0.0 and 1.0.",
                    parts + ["confidence"],
                )
        if "status" in value and value["status"] not in ("proposed", "approved"):
            _add(report, parsed, file, "schema", "SDL-E205", "Invalid inference status.", parts + ["status"])
        return

    # unresolved
    if any(key in value for key in ("type", "status", "confidence")):
        _add(
            report,
            parsed,
            file,
            "schema",
            "SDL-E407",
            "Unresolved type must not carry type, status or confidence.",
            parts,
        )
    _check_object(
        report,
        parsed,
        file,
        value,
        parts,
        UNRESOLVED_FIELDS,
        {"origin", "reason"},
        label,
    )
    if "reason" in value and (not isinstance(value["reason"], str) or not value["reason"]):
        _add(report, parsed, file, "schema", "SDL-E205", "reason must be a non-empty string.", parts + ["reason"])


def _check_imports(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
    project: bool,
) -> None:
    if not isinstance(value, list):
        _add(report, parsed, file, "schema", "SDL-E205", "imports must be a list.", parts)
        return
    for index, item in enumerate(value):
        item_parts = parts + [index]
        if not isinstance(item, dict):
            _add(report, parsed, file, "schema", "SDL-E205", "Import must be a mapping.", item_parts)
            continue
        if project:
            _check_object(
                report,
                parsed,
                file,
                item,
                item_parts,
                {"path"},
                {"path"},
                "project import",
            )
            if "path" in item and normalize_import_path(item["path"]) is None:
                _add(
                    report,
                    parsed,
                    file,
                    "schema",
                    "SDL-E300",
                    "Invalid project import path.",
                    item_parts + ["path"],
                )
            continue

        if "path" in item:
            _add(
                report,
                parsed,
                file,
                "schema",
                "SDL-E203",
                "Module imports cannot use path.",
                item_parts + ["path"],
            )
        if "module" in item and "package" in item:
            _add(
                report,
                parsed,
                file,
                "schema",
                "SDL-E203",
                "Import must be either module or package, not both.",
                item_parts,
            )
        if "module" not in item and "package" not in item:
            _add(
                report,
                parsed,
                file,
                "schema",
                "SDL-E204",
                "Module import requires module or package.",
                item_parts,
            )
        if "module" in item:
            _check_object(
                report,
                parsed,
                file,
                item,
                item_parts,
                {"module"},
                {"module"},
                "module import",
            )
            _check_id(report, parsed, file, item["module"], item_parts + ["module"], SNAKE_ID, "module")
        if "package" in item:
            _check_object(
                report,
                parsed,
                file,
                item,
                item_parts,
                {"package", "version"},
                {"package", "version"},
                "package import",
            )
            _check_id(report, parsed, file, item["package"], item_parts + ["package"], PACKAGE_ID, "package")
            if "version" in item and not valid_range(item["version"]):
                _add(
                    report,
                    parsed,
                    file,
                    "schema",
                    "SDL-E220",
                    "Invalid package version range.",
                    item_parts + ["version"],
                )


def _check_type_declaration(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
) -> None:
    if not isinstance(value, dict):
        _add(report, parsed, file, "schema", "SDL-E408", "Type declaration must be a mapping.", parts)
        return
    if "id" not in value:
        _add(report, parsed, file, "schema", "SDL-E204", "Type declaration requires id.", parts)
    if "id" in value:
        _check_id(report, parsed, file, value["id"], parts + ["id"], PASCAL_ID, "type")

    has_type = "type" in value
    has_enum = "enum" in value
    if has_type == has_enum:
        _add(
            report,
            parsed,
            file,
            "schema",
            "SDL-E408",
            "Type declaration requires exactly one of type or enum.",
            parts,
        )
    for key in value:
        if key not in TYPE_DECL_FIELDS:
            _add(
                report,
                parsed,
                file,
                "schema",
                "SDL-E408",
                f"Unknown field {key!r} in type declaration.",
                parts + [key],
            )
    if has_type:
        _check_type_expression(report, parsed, file, value["type"], parts + ["type"])
    if has_enum:
        enum = value["enum"]
        if not isinstance(enum, list) or not enum:
            _add(
                report,
                parsed,
                file,
                "schema",
                "SDL-E408",
                "Enum must be a non-empty list.",
                parts + ["enum"],
            )
            return
        for index, item in enumerate(enum):
            item_parts = parts + ["enum", index]
            _check_id(report, parsed, file, item, item_parts, SNAKE_ID, "enum value")
            if isinstance(item, str) and item.lower() in sdl_types.RESERVED_ENUM_VALUES:
                _add(
                    report,
                    parsed,
                    file,
                    "schema",
                    "SDL-E408",
                    "Enum value must not shadow a builtin type name.",
                    item_parts,
                )


def _check_types(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
) -> None:
    if not isinstance(value, list):
        _add(report, parsed, file, "schema", "SDL-E205", "types must be a list.", parts)
        return
    for index, item in enumerate(value):
        _check_type_declaration(report, parsed, file, item, parts + [index])


def _check_properties(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
    label: str,
) -> None:
    if not isinstance(value, dict):
        _add(report, parsed, file, "schema", "SDL-E205", f"{label} must be a mapping.", parts)
        return
    for name, type_value in value.items():
        name_parts = parts + [name]
        _check_id(report, parsed, file, name, name_parts, SNAKE_ID, label)
        _check_type_or_inference(report, parsed, file, type_value, name_parts, label)


def _check_output(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
) -> None:
    if not isinstance(value, dict):
        _add(report, parsed, file, "schema", "SDL-E205", "output must be a mapping.", parts)
        return
    _check_object(report, parsed, file, value, parts, OUTPUT_FIELDS, {"type"}, "output")
    if "type" in value:
        _check_type_expression(report, parsed, file, value["type"], parts + ["type"])


def _check_callable(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
    label: str,
) -> None:
    if not _check_object(
        report,
        parsed,
        file,
        value,
        parts,
        FUNCTION_FIELDS,
        {"id", "output"},
        label,
    ):
        return
    _check_id(report, parsed, file, value.get("id"), parts + ["id"], SNAKE_ID, label)
    if "input" in value:
        _check_properties(report, parsed, file, value["input"], parts + ["input"], "input")
    if "output" in value:
        _check_output(report, parsed, file, value["output"], parts + ["output"])


def _check_class(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
) -> None:
    if not _check_object(
        report,
        parsed,
        file,
        value,
        parts,
        CLASS_FIELDS,
        {"id"},
        "class",
    ):
        return
    _check_id(report, parsed, file, value.get("id"), parts + ["id"], PASCAL_ID, "class")
    if "properties" in value:
        _check_properties(report, parsed, file, value["properties"], parts + ["properties"], "property")


def _check_interface(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
) -> None:
    if not _check_object(
        report,
        parsed,
        file,
        value,
        parts,
        INTERFACE_FIELDS,
        {"id", "version"},
        "interface",
    ):
        return
    _check_id(report, parsed, file, value.get("id"), parts + ["id"], PASCAL_ID, "interface")
    _check_exact_version(report, parsed, file, value.get("version"), parts + ["version"], "interface version")
    if "methods" in value:
        methods = value["methods"]
        if not isinstance(methods, list):
            _add(report, parsed, file, "schema", "SDL-E205", "methods must be a list.", parts + ["methods"])
        else:
            for index, method in enumerate(methods):
                _check_callable(report, parsed, file, method, parts + ["methods", index], "method")


def _check_project(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
) -> None:
    if not _check_object(
        report,
        parsed,
        file,
        value,
        parts,
        PROJECT_FIELDS,
        {"id", "version"},
        "project",
    ):
        return
    _check_id(report, parsed, file, value.get("id"), parts + ["id"], SNAKE_ID, "project")
    _check_exact_version(report, parsed, file, value.get("version"), parts + ["version"], "project version")
    if "mode" in value:
        _check_mode(report, parsed, file, value["mode"], parts + ["mode"])
    if "imports" in value:
        _check_imports(report, parsed, file, value["imports"], parts + ["imports"], project=True)
    if "types" in value:
        _check_types(report, parsed, file, value["types"], parts + ["types"])
    if "interfaces" in value:
        interfaces = value["interfaces"]
        if not isinstance(interfaces, list):
            _add(report, parsed, file, "schema", "SDL-E205", "interfaces must be a list.", parts + ["interfaces"])
        else:
            for index, interface in enumerate(interfaces):
                _check_interface(report, parsed, file, interface, parts + ["interfaces", index])


def _check_module(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    value: Any,
    parts: list[Any],
) -> None:
    if not _check_object(
        report,
        parsed,
        file,
        value,
        parts,
        MODULE_FIELDS,
        {"id"},
        "module",
    ):
        return
    _check_id(report, parsed, file, value.get("id"), parts + ["id"], SNAKE_ID, "module")
    if "mode" in value:
        _check_mode(report, parsed, file, value["mode"], parts + ["mode"])
    if "imports" in value:
        _check_imports(report, parsed, file, value["imports"], parts + ["imports"], project=False)
    if "types" in value:
        _check_types(report, parsed, file, value["types"], parts + ["types"])
    if "interfaces" in value:
        interfaces = value["interfaces"]
        if not isinstance(interfaces, list):
            _add(report, parsed, file, "schema", "SDL-E205", "interfaces must be a list.", parts + ["interfaces"])
        else:
            for index, interface in enumerate(interfaces):
                _check_interface(report, parsed, file, interface, parts + ["interfaces", index])
    if "classes" in value:
        classes = value["classes"]
        if not isinstance(classes, list):
            _add(report, parsed, file, "schema", "SDL-E205", "classes must be a list.", parts + ["classes"])
        else:
            for index, item in enumerate(classes):
                _check_class(report, parsed, file, item, parts + ["classes", index])
    if "functions" in value:
        functions = value["functions"]
        if not isinstance(functions, list):
            _add(report, parsed, file, "schema", "SDL-E205", "functions must be a list.", parts + ["functions"])
        else:
            for index, item in enumerate(functions):
                _check_callable(report, parsed, file, item, parts + ["functions", index], "function")


def _validate_schema_0_2(parsed: ParsedDocument, file: str, report: Report) -> str | None:
    """Run envelope and shape checks for a Core 0.2 document."""

    data = parsed.data
    if not isinstance(data, dict):
        _add(report, parsed, file, "schema", "SDL-E200", "Document must be a mapping.", [])
        return None

    sdl = data.get("sdl")
    sdl_node = _node(parsed, ["sdl"])
    if sdl is None:
        _add(report, parsed, file, "schema", "SDL-E200", "Missing required field 'sdl'.", [])
    elif not isinstance(sdl, str) or not is_double_quoted(sdl_node) or sdl != "0.2":
        _add(
            report,
            parsed,
            file,
            "schema",
            "SDL-E200",
            "sdl must be the double-quoted string \"0.2\".",
            ["sdl"],
        )

    kind = data.get("kind")
    kind_node = _node(parsed, ["kind"])
    if kind is None:
        _add(report, parsed, file, "schema", "SDL-E201", "Missing required field 'kind'.", [])
    elif not isinstance(kind, str) or not is_string_node(kind_node):
        _add(report, parsed, file, "schema", "SDL-E201", "kind must be a string.", ["kind"])
        kind = None
    elif kind not in KINDS_0_2:
        _add(report, parsed, file, "schema", "SDL-E201", f"Unknown kind {kind!r}.", ["kind"])
        kind = None

    if kind is not None:
        if kind not in data:
            _add(
                report,
                parsed,
                file,
                "schema",
                "SDL-E202",
                f"Missing root key {kind!r} for kind {kind!r}.",
                [],
            )
        for key in data:
            if key not in TOP_FIELDS | {kind}:
                _add(
                    report,
                    parsed,
                    file,
                    "schema",
                    "SDL-E202",
                    f"Unexpected top-level key {key!r}.",
                    [key],
                )
        root_value = data.get(kind)
        if root_value is not None:
            if kind == "project":
                _check_project(report, parsed, file, root_value, [kind])
            elif kind == "module":
                _check_module(report, parsed, file, root_value, [kind])
            elif kind == "interface":
                _check_interface(report, parsed, file, root_value, [kind])
            else:
                if not isinstance(root_value, list):
                    _add(
                        report,
                        parsed,
                        file,
                        "schema",
                        "SDL-E205",
                        "types root must be a list.",
                        [kind],
                    )
                elif not root_value:
                    _add(
                        report,
                        parsed,
                        file,
                        "schema",
                        "SDL-E408",
                        "types root must not be empty.",
                        [kind],
                    )
                else:
                    _check_types(report, parsed, file, root_value, [kind])

    return kind


#: Per-kind identifier grammar for Core 1.0 root objects.
_ID_PATTERN_1_0 = {
    "project": SNAKE_ID,
    "interface": PASCAL_ID,
    "implementation": SNAKE_ID,
    "flow": SNAKE_ID,
}


def detect_version(parsed: ParsedDocument) -> str | None:
    """Return the core version declared by the envelope of a document."""
    data = parsed.data
    if not isinstance(data, dict):
        return None
    value = data.get("sdl")
    return value if isinstance(value, str) else None


def validate_schema(
    parsed: ParsedDocument,
    file: str,
    report: Report,
    version: str | None = None,
) -> str | None:
    """Run envelope and shape checks for the declared core version.

    Returns the document kind when it is known.
    """
    if version is None:
        version = detect_version(parsed)

    if version == "0.2":
        return _validate_schema_0_2(parsed, file, report)
    if version == "1.0":
        return _validate_schema_1_0(parsed, file, report)

    if version is None:
        _add(report, parsed, file, "schema", "SDL-E200", "Missing required field 'sdl'.", [])
    else:
        _add(
            report,
            parsed,
            file,
            "schema",
            "SDL-E200",
            f'sdl must be the double-quoted string "0.2" or "1.0", got {version!r}.',
            ["sdl"],
        )
    return None


def _validate_schema_1_0(parsed: ParsedDocument, file: str, report: Report) -> str | None:
    """Run envelope and shape checks for a Core 1.0 document."""
    data = parsed.data
    if not isinstance(data, dict):
        _add(report, parsed, file, "schema", "SDL-E200", "Document must be a mapping.", [])
        return None

    sdl = data.get("sdl")
    sdl_node = _node(parsed, ["sdl"])
    if sdl is None:
        _add(report, parsed, file, "schema", "SDL-E200", "Missing required field 'sdl'.", [])
    elif not isinstance(sdl, str) or not is_double_quoted(sdl_node) or sdl != "1.0":
        _add(
            report,
            parsed,
            file,
            "schema",
            "SDL-E200",
            'sdl must be the double-quoted string "1.0".',
            ["sdl"],
        )

    kind = data.get("kind")
    kind_node = _node(parsed, ["kind"])
    if kind is None:
        _add(report, parsed, file, "schema", "SDL-E201", "Missing required field 'kind'.", [])
    elif not isinstance(kind, str) or not is_string_node(kind_node):
        _add(report, parsed, file, "schema", "SDL-E201", "kind must be a string.", ["kind"])
        kind = None
    elif kind not in KINDS_1_0:
        _add(report, parsed, file, "schema", "SDL-E201", f"Unknown kind {kind!r}.", ["kind"])
        kind = None

    if kind is not None:
        if kind not in data:
            _add(
                report,
                parsed,
                file,
                "schema",
                "SDL-E202",
                f"Missing root key {kind!r} for kind {kind!r}.",
                [],
            )
        for key in data:
            if key not in TOP_FIELDS | {kind}:
                _add(
                    report,
                    parsed,
                    file,
                    "schema",
                    "SDL-E202",
                    f"Unexpected top-level key {key!r}.",
                    [key],
                )
        root_value = data.get(kind)
        if root_value is not None:
            _check_root_1_0(report, parsed, file, kind, root_value, [kind])

    return kind


def _check_root_1_0(
    report: Report,
    parsed: ParsedDocument,
    file: str,
    kind: str,
    root_value: Any,
    parts: list[Any],
) -> None:
    """Core 1.0 root checks that JSON Schema cannot express."""
    if kind == "types":
        if not isinstance(root_value, dict) or not root_value:
            _add(
                report,
                parsed,
                file,
                "schema",
                "SDL-E205",
                "types root must be a non-empty mapping.",
                parts,
            )
        return

    if kind not in _ID_PATTERN_1_0:
        return

    if not isinstance(root_value, dict):
        _add(report, parsed, file, "schema", "SDL-E205", f"{kind} must be a mapping.", parts)
        return

    _check_id(report, parsed, file, root_value.get("id"), parts + ["id"], _ID_PATTERN_1_0[kind], kind)
    if "version" in root_value:
        _check_exact_version(
            report,
            parsed,
            file,
            root_value["version"],
            parts + ["version"],
            f"{kind} version",
        )


#: JSON Schema keywords that only group other errors.
_COMBINATORS = ("oneOf", "anyOf", "allOf", "if", "then", "else")


def _best_error(error: Any) -> Any:
    """Descend into conditional errors to the most specific cause.

    A JSON Schema ``if``/``then`` construct reports its failure at the ``if``
    keyword, and ``oneOf`` reports a failure at the ``oneOf`` keyword. In both
    cases the actual cause is in ``context``. Without descending, every such
    failure would be reported as a generic shape error instead of the precise
    code.
    """
    if error.validator in _COMBINATORS and error.context:
        leaves = []
        for sub in error.context:
            candidate = _best_error(sub)
            if candidate.validator not in _COMBINATORS:
                leaves.append(candidate)
        if leaves:
            # The deepest cause is the most specific one. On a tie the first
            # branch wins, which follows the order of the schema definitions.
            return max(leaves, key=lambda item: len(item.absolute_path))
    return error


def _schema_error_code(error: Any) -> str:
    validator = error.validator
    path = list(error.absolute_path)
    last = str(path[-1]) if path else ""
    if validator == "required":
        return "SDL-E204"
    if validator == "additionalProperties":
        return "SDL-E203"
    if validator == "const":
        return "SDL-E200" if last == "sdl" else "SDL-E205"
    if validator == "enum":
        if last == "kind":
            return "SDL-E201"
        return "SDL-E205"
    if validator == "pattern":
        if last == "id":
            return "SDL-E210"
        if last == "version":
            return "SDL-E220"
        if last == "type":
            return "SDL-E400"
        if last == "path":
            return "SDL-E300"
        if "enum" in path:
            return "SDL-E210"
        return "SDL-E205"
    if validator == "minItems":
        if last == "enum" or "types" in path:
            return "SDL-E408"
        return "SDL-E205"
    return "SDL-E205"


def validate_json_schema(
    parsed: ParsedDocument,
    file: str,
    report: Report,
    schema: dict[str, Any],
) -> None:
    validator = Draft202012Validator(schema)
    for raw in validator.iter_errors(parsed.data):
        error = _best_error(raw)
        parts = list(error.absolute_path)
        node = _node(parsed, parts)
        line, column = location(node)
        report.add(
            "schema",
            "error",
            _schema_error_code(error),
            error.message,
            file,
            line,
            column,
            json_pointer(parts),
        )
