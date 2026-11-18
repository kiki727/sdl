"""Put back the layout of a document that is re-serialised.

A proposal is a transaction over the *data* of the documents, and the data
carries neither comments nor blank lines: the YAML parser drops them. When a
merged document is written back it is therefore re-serialised from the data,
and the layout a human wrote — the comments, and the blank lines that group
the document — would be lost.

This module reads the comments and the blank lines out of the original text
and puts them back into the re-serialised text:

* the blank lines and the own-line comments above a node are emitted before
  that node, in the order they were written;
* a trailing comment is appended to the line of the node it annotates;
* a comment or a blank line that belongs to a node a patch removed is
  dropped, because there is no longer a node to hold it;
* a list element is addressed by its ``id`` when it has one, so a comment
  follows the element when a neighbour is removed.

The rest of the layout — indentation, quoting, line breaks — is the
toolchain's, because the document is re-serialised from its data.

The reading is deliberately simple, because the SDL YAML subset is simple:
tabs, anchors, tags, flow collections and folded block scalars are already
forbidden (Core 0.2, ``sdl/yaml/subset.py``), so the only constructs this has
to understand are quoted scalars and literal block scalars.
"""

from __future__ import annotations

from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

#: A blank line of the layout, kept in the order it was written.
_BLANK = ("blank", "")


def _compose(text: str) -> Node | None:
    try:
        return yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None


def _lines(text: str) -> list[str]:
    """The lines of a document, without the empty string a final newline adds."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


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


def _continuation_lines(node: Node | None) -> set[int]:
    """The lines that are the body of a multi-line scalar.

    A ``#`` or a blank line inside a multi-line scalar — a literal block
    scalar, or a quoted scalar that spans several lines — is part of the
    value, not part of the layout, so those lines must be left alone. The
    first line of the scalar is the line of its key, which is where a trailing
    comment may live, so only the lines after it are skipped.
    """
    skip: set[int] = set()
    if isinstance(node, ScalarNode):
        if node.end_mark.line > node.start_mark.line:
            # A block scalar ends at the start of the line after its body; a
            # quoted or plain scalar ends on its last line, at the closing
            # quote. The first line is the line of the key, which is kept.
            if node.style in ("|", ">"):
                last = node.end_mark.line
            else:
                last = node.end_mark.line + 1
            for line in range(node.start_mark.line + 1, last):
                skip.add(line)
    elif isinstance(node, MappingNode):
        for _key_node, value_node in node.value:
            skip |= _continuation_lines(value_node)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            skip |= _continuation_lines(item)
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


def _prefixes(
    text: str, starts: dict[int, tuple], skip: set[int]
) -> tuple[dict[tuple, list], list]:
    """The blank lines and own-line comments that precede each node."""
    lines = _lines(text)
    prefix: dict[tuple, list] = {}
    pending: list = []
    for index, line in enumerate(lines):
        if index in skip:
            continue
        marker = _split_comment(line)
        content = line[:marker] if marker is not None else line
        if not content.strip():
            if marker is not None:
                pending.append(("comment", line[marker:].rstrip()))
            else:
                pending.append(_BLANK)
            continue
        path = starts.get(index)
        if path is not None:
            if pending:
                prefix[path] = list(pending)
            pending = []
    return prefix, list(pending)


def _trailing_comments(
    text: str, starts: dict[int, tuple], skip: set[int]
) -> dict[tuple, list[str]]:
    """The comments that share a line with the node they annotate."""
    lines = _lines(text)
    ordered = sorted(starts.items())
    trailing: dict[tuple, list[str]] = {}
    for index, line in enumerate(lines):
        if index in skip:
            continue
        marker = _split_comment(line)
        if marker is None or not line[:marker].strip():
            continue
        path = _path_at(ordered, index)
        trailing.setdefault(path, []).append(line[marker:].rstrip())
    return trailing


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" "))]


def restore_layout(original: str, rendered: str) -> str:
    """Re-attach the layout of ``original`` to the re-serialised ``rendered``.

    The blank lines and the own-line comments of a node are emitted before the
    node; a trailing comment is appended to the line of the node. A comment or
    a blank line whose node the change removed is dropped. The rest of
    ``rendered`` is left as it is.
    """
    tree = _compose(original)
    if tree is None:
        return rendered
    starts: dict[int, tuple] = {}
    _collect_starts(tree, (), starts)
    skip = _continuation_lines(tree)

    prefix, tail = _prefixes(original, starts, skip)
    trailing = _trailing_comments(original, starts, skip)
    if not prefix and not trailing and not tail:
        return rendered

    rendered_tree = _compose(rendered)
    if rendered_tree is None:
        return rendered
    paths: dict[tuple, int] = {}
    _collect_paths(rendered_tree, (), paths)

    lines = _lines(rendered)
    before: dict[int, list[str]] = {}
    after: dict[int, list[str]] = {}

    for path, items in prefix.items():
        line = paths.get(path)
        if line is None:
            continue
        indent = _indent_of(lines[line])
        before.setdefault(line, []).extend(
            "" if kind == "blank" else indent + text for kind, text in items
        )

    for path, texts in trailing.items():
        line = paths.get(path)
        if line is None:
            continue
        after.setdefault(line, []).extend(texts)

    out: list[str] = []
    for index, line in enumerate(lines):
        out.extend(before.get(index, ()))
        if index in after:
            out.append(line.rstrip() + "  " + "  ".join(after[index]))
        else:
            out.append(line)
    out.extend("" if kind == "blank" else text for kind, text in tail)

    result = "\n".join(out)
    if rendered.endswith("\n"):
        result += "\n"
    return result
