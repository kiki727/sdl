"""Put the comments of a document back after it is re-serialised.

A proposal is a transaction over the *data* of the documents, and the data
carries no comments: the YAML parser drops them. When a merged document is
written back it is therefore re-serialised from the data, and the comments a
human wrote would be lost.

This module reads the comments out of the original text and puts them back
into the re-serialised text, attached to the same node. A comment that
annotates a node the proposal removed is dropped, because there is no longer
a node to annotate; a comment that annotates a node the proposal kept is
preserved, wherever that node ended up in the new text.

The reading is deliberately simple, because the SDL YAML subset is simple:
tabs, anchors, tags, flow collections and folded block scalars are already
forbidden (Core 0.2, ``sdl/yaml/subset.py``), so the only constructs this has
to understand are quoted scalars and literal block scalars.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

#: A literal block scalar starts with ``|`` (or ``>``) that follows a key or a
#: sequence dash, optionally with a chomping or indentation indicator.
_BLOCK_INDICATOR = re.compile(r"(?:^|:\s+|-\s+)[|>][0-9+-]{0,2}\s*$")


@dataclass(frozen=True)
class Comment:
    """One comment of a document, and the node it annotates."""

    #: The path of the node the comment belongs to, or ``()`` for a comment
    #: that follows every node of the document.
    path: tuple[Any, ...]
    #: The comment text, including the leading ``#``.
    text: str
    #: True when the comment shares its line with content (a trailing
    #: comment), false when it has a line of its own.
    inline: bool


def _compose(text: str) -> Node | None:
    try:
        return yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None


def _split_comment(line: str) -> int | None:
    """The index of the ``#`` that starts a comment, or None.

    A ``#`` starts a comment only at the start of the line or after
    whitespace, and never inside a quoted scalar.
    """
    quote: str | None = None
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if quote is not None:
            if quote == '"' and char == "\\":
                index += 2
                continue
            if quote == "'" and char == "'" and index + 1 < length and line[index + 1] == "'":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            index += 1
            continue
        if char == "#" and (index == 0 or line[index - 1] in " \t"):
            return index
        index += 1
    return None


def _block_scalar_lines(lines: list[str]) -> set[int]:
    """The line numbers that are the body of a literal block scalar.

    A ``#`` inside a block scalar is part of the scalar, not a comment, so
    those lines must be left alone.
    """
    skip: set[int] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        marker = _split_comment(line)
        content = line[:marker] if marker is not None else line
        if not _BLOCK_INDICATOR.search(content):
            index += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            if not candidate.strip():
                skip.add(cursor)
                cursor += 1
                continue
            current = len(candidate) - len(candidate.lstrip(" "))
            if current <= indent:
                break
            skip.add(cursor)
            cursor += 1
        index = cursor
    return skip


def _item_segment(index: int, item: Node) -> Any:
    """The path segment of a sequence item.

    An item that is a mapping with a scalar ``id`` is addressed by that id
    rather than by its position, so that a comment follows the item when a
    proposal removes another one before it. Every other item is addressed by
    its index.
    """
    if isinstance(item, MappingNode):
        for key_node, value_node in item.value:
            if (
                isinstance(key_node, ScalarNode)
                and key_node.value == "id"
                and isinstance(value_node, ScalarNode)
            ):
                return ("id", value_node.value)
    return index


def _collect_starts(node: Node | None, path: tuple[Any, ...], out: dict[int, tuple]) -> None:
    """Map the first line of every node to the path of that node."""
    if isinstance(node, MappingNode):
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                continue
            child = path + (key_node.value,)
            out.setdefault(key_node.start_mark.line, child)
            _collect_starts(value_node, child, out)
    elif isinstance(node, SequenceNode):
        for index, item in enumerate(node.value):
            child = path + (_item_segment(index, item),)
            out.setdefault(item.start_mark.line, child)
            _collect_starts(item, child, out)


def _collect_paths(node: Node | None, path: tuple[Any, ...], out: dict[tuple, int]) -> None:
    """Map the path of every node to the first line of that node."""
    if isinstance(node, MappingNode):
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                continue
            child = path + (key_node.value,)
            out.setdefault(child, key_node.start_mark.line)
            _collect_paths(value_node, child, out)
    elif isinstance(node, SequenceNode):
        for index, item in enumerate(node.value):
            child = path + (_item_segment(index, item),)
            out.setdefault(child, item.start_mark.line)
            _collect_paths(item, child, out)


def _path_at(ordered: list[tuple[int, tuple]], line: int) -> tuple:
    """The path of the node that owns ``line``."""
    found: tuple = ()
    for start, path in ordered:
        if start <= line:
            found = path
        else:
            break
    return found


def _path_after(ordered: list[tuple[int, tuple]], line: int) -> tuple:
    """The path of the next node that starts after ``line``."""
    for start, path in ordered:
        if start > line:
            return path
    return ()


def extract_comments(text: str, tree: Node | None = None) -> list[Comment]:
    """The comments of a document, each attached to the node it annotates."""
    if tree is None:
        tree = _compose(text)
    starts: dict[int, tuple] = {}
    _collect_starts(tree, (), starts)
    ordered = sorted(starts.items())

    lines = text.split("\n")
    skip = _block_scalar_lines(lines)
    comments: list[Comment] = []
    for index, line in enumerate(lines):
        if index in skip:
            continue
        marker = _split_comment(line)
        if marker is None:
            continue
        body = line[marker:].rstrip()
        if line[:marker].strip():
            comments.append(Comment(path=_path_at(ordered, index), text=body, inline=True))
        else:
            comments.append(Comment(path=_path_after(ordered, index), text=body, inline=False))
    return comments


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" "))]


def restore_comments(original: str, rendered: str) -> str:
    """Re-attach the comments of ``original`` to the re-serialised ``rendered``.

    A comment whose node survived the change is put back beside that node; a
    comment whose node is gone is dropped. The layout of ``rendered`` is left
    as it is: only comment lines are inserted, and only trailing comments are
    appended to a line.
    """
    tree = _compose(original)
    comments = extract_comments(original, tree)
    if not comments:
        return rendered

    rendered_tree = _compose(rendered)
    if rendered_tree is None:
        return rendered
    paths: dict[tuple, int] = {}
    _collect_paths(rendered_tree, (), paths)

    lines = rendered.split("\n")
    before: dict[int, list[str]] = {}
    after: dict[int, list[str]] = {}
    tail: list[str] = []

    for comment in comments:
        line = paths.get(comment.path)
        if line is None:
            if not comment.path:
                tail.append(comment.text)
            continue
        if comment.inline:
            after.setdefault(line, []).append(comment.text)
        else:
            before.setdefault(line, []).append(_indent_of(lines[line]) + comment.text)

    out: list[str] = []
    for index, line in enumerate(lines):
        out.extend(before.get(index, ()))
        if index in after:
            out.append(line.rstrip() + "  " + "  ".join(after[index]))
        else:
            out.append(line)
    out.extend(tail)
    return "\n".join(out)
