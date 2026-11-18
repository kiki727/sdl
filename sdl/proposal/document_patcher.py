"""Applying patches to a shadow copy of the documents.

A proposal is applied to a copy of the document set, never to the documents
themselves. The copy is validated, and only a proposal that passes every
validation phase and carries an approval is merged back.
"""

from __future__ import annotations

from typing import Any

from sdl.documents import DocumentSet, SourceDocument
from sdl.proposal.models import Patch, PatchAction
from sdl.proposal.paths import (
    _MISSING,
    TargetError,
    find_item,
    parent_of,
    parse_target,
    resolve,
    select_document,
)


class DocumentPatchError(Exception):
    """A patch that could not be applied."""


class PatchConflictError(DocumentPatchError):
    """Two patches that change the same element of the specification."""


class DocumentPatcher:
    """Applies patches to a shadow copy of a document set."""

    def __init__(self, documents: DocumentSet):
        self.documents = documents

    # -- entry points --------------------------------------------------------

    def apply_patches(self, patches: list[Patch]) -> None:
        """Apply a sequence of patches."""
        self.validate_conflicts(patches)
        for patch in patches:
            self.apply_patch(patch)

    def validate_conflicts(self, patches: list[Patch]) -> None:
        """Reject two patches that touch the same element.

        Two targets may be written differently and still name the same
        element: ``project.bindings`` and ``project.sdl.yaml:bindings`` are the
        same list, and ``flow.sdl.yaml:version`` and ``flow.my_flow.version``
        are the same key. The identity of a target is therefore the document
        it selects plus its pointer, not the string the proposal wrote.
        """
        seen: dict[tuple[str, tuple[str, ...]], Patch] = {}
        for patch in patches:
            identity = self._identity(patch)
            if identity in seen:
                raise PatchConflictError(
                    f"Two patches target {patch.target!r}. A proposal may not "
                    f"change the same element twice."
                )
            seen[identity] = patch

    def _identity(self, patch: Patch) -> tuple[str, tuple[str, ...]]:
        """The canonical identity of the element a patch names."""
        try:
            target = parse_target(patch.target)
        except TargetError as error:
            # Let apply_patch report the invalid target with its own message.
            return ("<unparsed>", (patch.target,))
        document = self._select(target)
        if document is None:
            return ("<unknown>", (patch.target,))
        return (
            document.relative,
            tuple(f"{segment.kind}:{segment.value}" for segment in target.segments),
        )

    def apply_patch(self, patch: Patch) -> None:
        """Apply one patch."""
        try:
            target = parse_target(patch.target)
        except TargetError as error:
            raise DocumentPatchError(str(error)) from error

        document = self._select(target)
        if document is None:
            raise DocumentPatchError(
                f"The target {patch.target!r} does not name a document of the project."
            )

        root = document.root
        if root is None:
            raise DocumentPatchError(
                f"The document {document.relative!r} has no root to patch."
            )

        try:
            if patch.action == PatchAction.ADD:
                self._add(root, target, patch.value)
            elif patch.action == PatchAction.REPLACE:
                self._replace(root, target, patch.value)
            elif patch.action == PatchAction.REMOVE:
                self._remove(root, target)
        except TargetError as error:
            raise DocumentPatchError(str(error)) from error

    # -- selection -----------------------------------------------------------

    def _select(self, target) -> SourceDocument | None:
        """Find the document a target names."""
        return select_document(self.documents, target)

    # -- actions -------------------------------------------------------------

    def _add(self, root: Any, target, value: Any) -> None:
        """Add a new element to a list, or a new field to a mapping.

        Specification section 8.3: ``add`` *adds a new element to a list or a
        new field to an object*. The target therefore names the collection
        that receives the value, not the position of the new value.
        """
        current = resolve(root, target.segments)

        # The target names a list: the value is a new element of that list.
        if isinstance(current, list):
            segment = target.segments[-1]
            if segment.kind == "index":
                position = int(segment.value)
                if not 0 <= position <= len(current):
                    raise TargetError(
                        f"The index {position} is outside the list at {target.raw!r}."
                    )
                current.insert(position, value)
                return
            current.append(value)
            return

        # The target names a mapping: the value is a set of new fields.
        if isinstance(current, dict):
            if not isinstance(value, dict):
                raise TargetError(
                    f"The target {target.raw!r} names a mapping, so the value must be a "
                    f"mapping of fields."
                )
            for name, item in value.items():
                current[name] = item
            return

        # The target names something that exists and is not a collection, so
        # there is nothing to add to it.
        if current is not _MISSING:
            raise TargetError(
                f"The target {target.raw!r} already exists and is not a collection. "
                f"Use 'replace' to change it."
            )

        # The target does not exist yet: the parent receives the new field.
        container, segment = parent_of(root, target.segments)
        if container is _MISSING:
            raise TargetError(
                f"The target {target.raw!r} does not exist, so nothing can be added to it."
            )

        if isinstance(container, dict):
            container[segment.value] = value
            return

        if isinstance(container, list):
            if segment.kind == "index":
                position = int(segment.value)
                if not 0 <= position <= len(container):
                    raise TargetError(
                        f"The index {position} is outside the list at {target.raw!r}."
                    )
                container.insert(position, value)
                return
            container.append(value)
            return

        raise TargetError(f"The target {target.raw!r} does not name a collection.")

    def _replace(self, root: Any, target, value: Any) -> None:
        current = resolve(root, target.segments)
        if current is _MISSING:
            raise TargetError(f"The target {target.raw!r} does not exist.")

        container, segment = parent_of(root, target.segments)
        if container is _MISSING:
            raise TargetError(f"The target {target.raw!r} does not exist.")

        if isinstance(container, dict):
            container[segment.value] = value
            return

        if isinstance(container, list):
            if segment.kind == "index":
                position = int(segment.value)
                if not 0 <= position < len(container):
                    raise TargetError(
                        f"The index {position} is outside the list at {target.raw!r}."
                    )
                container[position] = value
                return
            position = find_item(container, segment)
            if position is not None:
                container[position] = value
                return
            raise TargetError(f"The target {target.raw!r} does not exist.")

        raise TargetError(f"The target {target.raw!r} does not name a collection.")

    def _remove(self, root: Any, target) -> None:
        current = resolve(root, target.segments)
        if current is _MISSING:
            raise TargetError(f"The target {target.raw!r} does not exist.")

        container, segment = parent_of(root, target.segments)
        if container is _MISSING:
            raise TargetError(f"The target {target.raw!r} does not exist.")

        if isinstance(container, dict):
            container.pop(segment.value, None)
            return

        if isinstance(container, list):
            if segment.kind == "index":
                position = int(segment.value)
                if 0 <= position < len(container):
                    container.pop(position)
                    return
                raise TargetError(f"The index {position} is outside the list at {target.raw!r}.")
            position = find_item(container, segment)
            if position is not None:
                container.pop(position)
                return
            raise TargetError(f"The target {target.raw!r} does not exist.")

        raise TargetError(f"The target {target.raw!r} does not name a collection.")
