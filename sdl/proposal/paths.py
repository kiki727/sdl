"""The target syntax of a patch.

Specification section 8.3 defines the target of a patch as a path to an
element of the specification, with the syntax ``object.field`` or
``list[index]``.

Two forms are accepted:

* ``<kind>.<id>.<pointer>`` or ``<kind>.<pointer>`` — the document is named by
  its kind and, when it has one, its identifier. For example
  ``project.bindings[PaymentProvider]`` or ``module.payment_logic.imports``.
* ``<file>:<pointer>`` — the document is named by its path relative to the
  project root, and the pointer follows a colon. For example
  ``types.sdl.yaml:HeroContent.fields``.

The pointer is relative to the root object of the document, that is to the
value of the ``kind`` key. A segment is either ``.name`` for a key of a
mapping, or ``[name]`` for a key of a mapping or for the element of a list
whose ``id`` is ``name``, or ``[3]`` for the third element of a list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: The document kinds a target may name.
KINDS = ("project", "types", "module", "interface", "flow", "implementation")

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class TargetError(Exception):
    """A target that cannot be understood."""


@dataclass
class Segment:
    """One step of a pointer."""

    kind: str  # "key" or "index"
    value: str

    def __str__(self) -> str:
        return f".{self.value}" if self.kind == "key" else f"[{self.value}]"


@dataclass
class Target:
    """The parsed target of a patch."""

    raw: str
    kind: str | None = None
    identifier: str | None = None
    file: str | None = None
    segments: list[Segment] = field(default_factory=list)

    @property
    def is_file_form(self) -> bool:
        return self.file is not None

    def __str__(self) -> str:
        selector = self.file if self.file is not None else ".".join(
            part for part in (self.kind, self.identifier) if part
        )
        if self.file is not None:
            return f"{selector}:{''.join(str(segment) for segment in self.segments)}"
        return selector + "".join(str(segment) for segment in self.segments)


def parse_pointer(text: str) -> list[Segment]:
    """Parse a pointer into its segments.

    The first segment is a bare name, the way specification section 8.3
    writes it: ``bindings[PaymentProvider]``. Every further segment is either
    ``.name`` or ``[name]`` or ``[3]``.
    """
    if not text:
        raise TargetError("A pointer must not be empty.")

    segments: list[Segment] = []
    position = 0

    match = _NAME.match(text, position)
    if not match:
        raise TargetError(f"Invalid pointer {text!r} at position {position}.")
    segments.append(Segment("key", match.group()))
    position = match.end()

    while position < len(text):
        char = text[position]
        if char == ".":
            match = _NAME.match(text, position + 1)
            if not match:
                raise TargetError(f"Invalid pointer {text!r} at position {position}.")
            segments.append(Segment("key", match.group()))
            position = match.end()
            continue

        if char == "[":
            end = text.find("]", position)
            if end == -1:
                raise TargetError(f"Unterminated index in the pointer {text!r}.")
            inner = text[position + 1 : end]
            if inner.isdigit():
                segments.append(Segment("index", inner))
            elif inner:
                segments.append(Segment("key", inner))
            else:
                raise TargetError(f"Invalid pointer {text!r}: an empty index.")
            position = end + 1
            continue

        raise TargetError(f"Invalid pointer {text!r} at position {position}.")

    return segments


def parse_target(target: str) -> Target:
    """Parse the target of a patch."""
    if not isinstance(target, str) or not target.strip():
        raise TargetError("A patch must name a target.")

    raw = target.strip()

    if ":" in raw:
        selector, _, pointer_text = raw.partition(":")
        selector = selector.strip()
        if not selector:
            raise TargetError(f"The target {target!r} does not name a document.")
        return Target(
            raw=raw,
            file=selector,
            segments=parse_pointer(pointer_text),
        )

    head, separator, tail = raw.partition(".")
    if head in ("project", "types"):
        return Target(
            raw=raw,
            kind=head,
            segments=parse_pointer(raw[len(head):].lstrip(".")),
        )

    if head in KINDS and separator:
        identifier, _, rest = tail.partition(".")
        return Target(
            raw=raw,
            kind=head,
            identifier=identifier,
            segments=parse_pointer(rest),
        )

    raise TargetError(
        f"The target {target!r} does not name a document. Use "
        f"'<kind>.<path>' or '<file>:<path>'."
    )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve(document: Any, segments: list[Segment]) -> Any:
    """Resolve a pointer inside a document root."""
    current = document
    for segment in segments:
        current = _step(current, segment)
        if current is _MISSING:
            return _MISSING
    return current


class _Missing:
    """The result of a resolution that found nothing."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<missing>"


_MISSING = _Missing()


def _step(current: Any, segment: Segment) -> Any:
    if isinstance(current, dict):
        if segment.kind == "key":
            return current.get(segment.value, _MISSING)
        return _MISSING

    if isinstance(current, list):
        if segment.kind == "index":
            position = int(segment.value)
            if 0 <= position < len(current):
                return current[position]
            return _MISSING
        for item in current:
            if isinstance(item, dict) and _item_key(item) == segment.value:
                return item
        return _MISSING

    return _MISSING


#: The fields that may name an element of a list.
_ITEM_KEYS = ("id", "name", "interface", "key")


def _item_key(item: dict) -> str | None:
    """The name of an element of a list.

    Most elements are named by their ``id``. A binding of section 6.2 is named
    by the interface it binds, so the specification can address it as
    ``project.bindings[PaymentProvider]``.
    """
    for key in _ITEM_KEYS:
        value = item.get(key)
        if isinstance(value, str):
            return value
    return None


def find_item(container: list, segment: Segment) -> int | None:
    """The position of the element of a list a segment names."""
    if segment.kind == "index":
        position = int(segment.value)
        if 0 <= position < len(container):
            return position
        return None
    for position, item in enumerate(container):
        if isinstance(item, dict) and _item_key(item) == segment.value:
            return position
    return None


def parent_of(document: Any, segments: list[Segment]) -> tuple[Any, Segment]:
    """The container of the last segment of a pointer and the segment itself."""
    if not segments:
        raise TargetError("A patch must name a property.")
    current = document
    for segment in segments[:-1]:
        current = _step(current, segment)
        if current is _MISSING:
            return _MISSING, segments[-1]
    return current, segments[-1]


def select_document(documents: Any, target: Target) -> Any:
    """The document a target names, or None when there is none.

    The document set is duck typed on purpose: this module must not depend
    on the document layer.
    """
    if target.is_file_form:
        return documents.get(target.file)

    if target.kind == "project":
        return documents.project

    identifier = target.identifier
    for document in documents.documents.values():
        if document.kind != target.kind:
            continue
        root = document.root
        if not isinstance(root, dict):
            continue
        if identifier is None or root.get("id") == identifier:
            return document
    return None
