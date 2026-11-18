"""The document set of a project.

A project is a root ``project`` document plus every document it imports. The
set is the unit the proposal protocol works on: a proposal is applied to a
shadow copy of the set, the copy is validated, and the copy is merged back.

The set keeps the raw text of every document, so that a document that is not
changed by a proposal is written back byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

import yaml

from sdl.parser.ast import ASTNode
from sdl.parser.yaml_parser import SDLYamlParser, SDLParserError
from sdl.yaml.layout import restore_layout
from sdl.yaml.subset import parse_file

#: A string that looks like a version has to stay double quoted. The envelope
#: of Core 0.2 and Core 1.0 requires the ``sdl`` field and every ``version``
#: field to be a double quoted string, and a plain YAML scalar would lose
#: that when the document is written back.
_VERSION_LIKE = re.compile(r"^\d+\.\d+(\.\d+)?$")


class SDLDumper(yaml.SafeDumper):
    """A YAML dumper that keeps version strings double quoted.

    Sequences are indented under their key, which is the style the SDL
    documents are written in.
    """

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, False)


def _represent_string(dumper: yaml.Dumper, data: str):
    if _VERSION_LIKE.match(data):
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


SDLDumper.add_representer(str, _represent_string)


@dataclass
class SourceDocument:
    """One document of a project."""

    path: Path
    relative: str
    kind: str
    data: dict[str, Any]
    text: str
    ast: ASTNode | None = None

    @property
    def root(self) -> Any:
        """The value of the root key of the document."""
        return self.data.get(self.kind)

    @root.setter
    def root(self, value: Any) -> None:
        self.data[self.kind] = value

    def clone(self) -> "SourceDocument":
        """A copy that can be modified without touching the original."""
        import copy

        return SourceDocument(
            path=self.path,
            relative=self.relative,
            kind=self.kind,
            data=copy.deepcopy(self.data),
            text=self.text,
            ast=self.ast,
        )

    def render(self) -> str:
        """The document as YAML text.

        The data carries neither comments nor blank lines, so the comments
        and the blank lines of the original text are read out of it and put
        back around the nodes they belong to. A comment or a blank line whose
        node survived a change is preserved; one whose node is gone is
        dropped. See :mod:`sdl.yaml.layout`.
        """
        rendered = yaml.dump(
            self.data,
            Dumper=SDLDumper,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        return restore_layout(self.text, rendered)


@dataclass
class DocumentSet:
    """The documents of a project, keyed by their path."""

    root: Path
    entry: Path
    documents: dict[str, SourceDocument] = field(default_factory=dict)

    @property
    def project(self) -> SourceDocument | None:
        for document in self.documents.values():
            if document.kind == "project":
                return document
        return None

    def get(self, relative: str) -> SourceDocument | None:
        return self.documents.get(relative.replace("\\", "/"))

    def clone(self) -> "DocumentSet":
        """A shadow copy of the set."""
        return DocumentSet(
            root=self.root,
            entry=self.entry,
            documents={
                name: document.clone() for name, document in self.documents.items()
            },
        )

    def changed(self) -> list[SourceDocument]:
        """The documents whose content differs from the original."""
        original = DocumentSetLoader(self.root, self.entry).load()
        changed: list[SourceDocument] = []
        for name, document in sorted(self.documents.items()):
            before = original.get(name)
            if before is None or before.data != document.data:
                changed.append(document)
        return changed


class DocumentSetLoader:
    """Loads the documents of a project."""

    def __init__(self, root: Path, entry: Path):
        self.root = Path(root).resolve()
        self.entry = Path(entry).resolve()

    def load(self) -> DocumentSet:
        """Load the entry document and everything it imports."""
        documents: dict[str, SourceDocument] = {}
        queue: list[Path] = [self.entry]
        seen: set[Path] = set()

        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)

            document = self._load_one(current)
            if document is None:
                continue
            documents[document.relative] = document

            for relative in self._imports(document):
                target = (self.root / relative).resolve()
                if target not in seen:
                    queue.append(target)

        return DocumentSet(root=self.root, entry=self.entry, documents=documents)

    def _load_one(self, path: Path) -> SourceDocument | None:
        try:
            text = path.read_text(encoding="utf-8")
            parsed = parse_file(path)
        except OSError:
            return None
        except SDLParserError:
            return None

        data = parsed.data
        if not isinstance(data, dict):
            return None
        kind = data.get("kind")
        if not isinstance(kind, str):
            return None

        relative = self._relative(path)
        ast = None
        try:
            ast = SDLYamlParser(path.name).parse(text)
        except SDLParserError:
            ast = None

        return SourceDocument(
            path=path,
            relative=relative,
            kind=kind,
            data=data,
            text=text,
            ast=ast,
        )

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.name

    @staticmethod
    def _imports(document: SourceDocument) -> list[str]:
        root = document.root
        if not isinstance(root, dict):
            return []
        imports = root.get("imports")
        if not isinstance(imports, list):
            return []
        return [
            item["path"]
            for item in imports
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ]


def load_document_set(entry: Path) -> DocumentSet:
    """Load the document set of a project."""
    entry = Path(entry).resolve()
    return DocumentSetLoader(entry.parent, entry).load()
