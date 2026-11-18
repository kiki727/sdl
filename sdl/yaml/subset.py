"""YAML subset parser for SDL Core 0.2.

This module implements only the rules that must run before or beside JSON
Schema validation: UTF-8/no BOM, duplicate keys, anchors/aliases, merge keys,
multi-document files, flow style, tabs and scalar quoting. It is a reference
implementation for the conformance fixtures, not a production parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import (
    AliasToken,
    AnchorToken,
    DocumentEndToken,
    DocumentStartToken,
    FlowMappingEndToken,
    FlowMappingStartToken,
    FlowSequenceEndToken,
    FlowSequenceStartToken,
    ScalarToken,
    TagToken,
)

STR_TAG = "tag:yaml.org,2002:str"
MAX_SIZE = 1024 * 1024
MAX_DEPTH = 64


class SubsetError(Exception):
    """A rejected YAML subset construct."""

    def __init__(self, code: str, message: str, line: int = 1, column: int = 1):
        super().__init__(message)
        self.code = code
        self.message = message
        self.line = line
        self.column = column


@dataclass(frozen=True)
class ParsedDocument:
    data: Any
    root: Node
    text: str


def _mark_line(mark: Any) -> int:
    return getattr(mark, "line", 0) + 1


def _mark_column(mark: Any) -> int:
    return getattr(mark, "column", 0) + 1


def _check_indentation(text: str) -> None:
    for number, line in enumerate(text.splitlines(), 1):
        prefix = line[: len(line) - len(line.lstrip(" \t"))]
        if "\t" in prefix:
            raise SubsetError("SDL-E102", "Tabs are not allowed in indentation.", number, 1)


def _scan_tokens(text: str) -> None:
    try:
        tokens = list(yaml.scan(text))
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        raise SubsetError(
            "SDL-E100",
            f"YAML parse error: {getattr(error, 'problem', error)}",
            _mark_line(mark),
            _mark_column(mark),
        ) from error

    seen_document_start = False
    for index, token in enumerate(tokens):
        line = _mark_line(token.start_mark)
        column = _mark_column(token.start_mark)

        if isinstance(token, AnchorToken):
            raise SubsetError("SDL-E102", "YAML anchors are forbidden.", line, column)
        if isinstance(token, AliasToken):
            raise SubsetError("SDL-E102", "YAML aliases are forbidden.", line, column)
        if isinstance(token, TagToken):
            raise SubsetError("SDL-E102", "YAML tags are forbidden.", line, column)
        if isinstance(token, DocumentEndToken):
            raise SubsetError("SDL-E102", "Document end markers are forbidden.", line, column)
        if isinstance(token, DocumentStartToken):
            if seen_document_start:
                raise SubsetError("SDL-E102", "Multi-document files are forbidden.", line, column)
            seen_document_start = True
        if isinstance(token, ScalarToken) and token.style == ">":
            raise SubsetError("SDL-E102", "Folded block scalars are forbidden.", line, column)
        if isinstance(token, FlowSequenceStartToken):
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            if not isinstance(following, FlowSequenceEndToken):
                raise SubsetError(
                    "SDL-E102",
                    "Flow style is allowed only for the empty collection [].",
                    line,
                    column,
                )
        if isinstance(token, FlowMappingStartToken):
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            if not isinstance(following, FlowMappingEndToken):
                raise SubsetError(
                    "SDL-E102",
                    "Flow style is allowed only for the empty collection {}.",
                    line,
                    column,
                )


def _check_node(node: Node, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        mark = node.start_mark
        raise SubsetError(
            "SDL-E103",
            f"Maximum nesting depth of {MAX_DEPTH} exceeded.",
            _mark_line(mark),
            _mark_column(mark),
        )
    if getattr(node, "anchor", None) is not None:
        mark = node.start_mark
        raise SubsetError("SDL-E102", "YAML anchors are forbidden.", _mark_line(mark), _mark_column(mark))

    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                mark = key_node.start_mark
                raise SubsetError(
                    "SDL-E102",
                    "Complex mapping keys are forbidden.",
                    _mark_line(mark),
                    _mark_column(mark),
                )
            if key_node.value == "<<":
                mark = key_node.start_mark
                raise SubsetError(
                    "SDL-E102",
                    "Merge keys are forbidden.",
                    _mark_line(mark),
                    _mark_column(mark),
                )
            identity = (key_node.tag, key_node.value)
            if identity in seen:
                mark = key_node.start_mark
                raise SubsetError(
                    "SDL-E101",
                    f"Duplicate mapping key: {key_node.value!r}.",
                    _mark_line(mark),
                    _mark_column(mark),
                )
            seen.add(identity)
            _check_node(value_node, depth + 1)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            _check_node(item, depth + 1)


def parse_text(text: str) -> ParsedDocument:
    """Parse one SDL YAML document or raise SubsetError."""

    if text.startswith("\ufeff"):
        raise SubsetError("SDL-E102", "UTF-8 BOM is forbidden.")
    if len(text.encode("utf-8")) > MAX_SIZE:
        raise SubsetError("SDL-E103", "Maximum document size of 1 MiB exceeded.")

    _check_indentation(text)
    _scan_tokens(text)

    try:
        nodes: list[Node] = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        raise SubsetError(
            "SDL-E100",
            f"YAML parse error: {getattr(error, 'problem', error)}",
            _mark_line(mark),
            _mark_column(mark),
        ) from error

    if len(nodes) != 1:
        raise SubsetError("SDL-E102", "Exactly one YAML document per file is required.")
    root = nodes[0]
    _check_node(root)

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        raise SubsetError(
            "SDL-E100",
            f"YAML parse error: {getattr(error, 'problem', error)}",
            _mark_line(mark),
            _mark_column(mark),
        ) from error

    return ParsedDocument(data=data, root=root, text=text)


def parse_file(path: Any) -> ParsedDocument:
    with open(path, "rb") as handle:
        raw = handle.read()
    if len(raw) > MAX_SIZE:
        raise SubsetError("SDL-E103", "Maximum document size of 1 MiB exceeded.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SubsetError("SDL-E100", f"File is not valid UTF-8: {error}") from error
    return parse_text(text)


def node_at(root: Node, parts: Iterable[Any]) -> Node | None:
    node = root
    for part in parts:
        if isinstance(node, MappingNode):
            found = None
            for key_node, value_node in node.value:
                if isinstance(key_node, ScalarNode) and key_node.value == str(part):
                    found = value_node
                    break
            if found is None:
                return None
            node = found
        elif isinstance(node, SequenceNode):
            if not isinstance(part, int) or part < 0 or part >= len(node.value):
                return None
            node = node.value[part]
        else:
            return None
    return node


def location(node: Node | None) -> tuple[int, int]:
    if node is None:
        return 1, 1
    return _mark_line(node.start_mark), _mark_column(node.start_mark)


def is_quoted(node: Node | None) -> bool:
    return isinstance(node, ScalarNode) and node.style in {'"', "'"}


def is_double_quoted(node: Node | None) -> bool:
    return isinstance(node, ScalarNode) and node.style == '"'


def is_plain(node: Node | None) -> bool:
    return isinstance(node, ScalarNode) and node.style is None


def is_string_node(node: Node | None) -> bool:
    return isinstance(node, ScalarNode) and node.tag == STR_TAG


def node_tag(node: Node | None) -> str | None:
    return node.tag if isinstance(node, ScalarNode) else None
