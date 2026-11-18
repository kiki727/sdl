"""The registry of the SDL runtime.

The runtime never imports an implementation itself. It asks the registry for
the callable a step names, and the registry resolves that name through the
bindings of the project.

The registry can be filled in two ways:

* from the specification, with :meth:`Registry.from_project`, which imports
  the source file an implementation declares;
* by hand, with :meth:`Registry.register`, which is what a test or an
  application does when it provides its own implementation.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from sdl.backends.runtime.errors import UnknownTargetError


class Registry:
    """Holds the callables a flow names."""

    def __init__(self) -> None:
        self._items: Dict[str, Any] = {}

    def register(self, name: str, implementation: Any) -> None:
        """Register the implementation of a name."""
        self._items[name] = implementation

    def resolve(self, name: str) -> Any:
        """The implementation of a name.

        A class is instantiated the first time it is needed, and the instance
        is kept, so that a stateful implementation keeps its state.
        """
        try:
            item = self._items[name]
        except KeyError:
            raise UnknownTargetError(
                f"Nothing is registered for {name!r}. The bindings of the project "
                f"must provide it."
            ) from None
        if isinstance(item, type):
            item = item()
            self._items[name] = item
        return item

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def __len__(self) -> int:
        return len(self._items)

    def names(self) -> list[str]:
        """The names that are registered, in order."""
        return sorted(self._items)

    # -- from the specification ----------------------------------------------

    @classmethod
    def from_project(cls, graph: Any, root: Path) -> "Registry":
        """Build the registry of a project from its canonical IR.

        An implementation declares where its realization lives, and the
        runtime imports it. A module function is looked up in a Python module
        of the same name in the project root.
        """
        from sdl.ir.edges import EdgeKind
        from sdl.ir.symbols import (
            ImplementationSymbol,
            InterfaceSymbol,
            MethodSymbol,
            ModuleSymbol,
        )

        registry = cls()
        root = Path(root).resolve()

        for symbol in graph.symbols.values():
            if isinstance(symbol, ImplementationSymbol):
                implementation = _load_implementation(root, symbol)
                if implementation is None:
                    continue
                registry.register(symbol.qualified_name, implementation)
                for edge in graph.get_edges_from(symbol.id):
                    if edge.kind != EdgeKind.IMPLEMENTS:
                        continue
                    interface = graph.get_symbol(edge.target)
                    if isinstance(interface, InterfaceSymbol):
                        registry.register(interface.qualified_name, implementation)

        for symbol in graph.symbols.values():
            if not isinstance(symbol, MethodSymbol):
                continue
            if symbol.metadata.get("owner"):
                continue
            scope = symbol.metadata.get("scope")
            if not scope:
                continue
            function = _load_module_function(root, str(scope), symbol.name)
            if function is not None:
                registry.register(symbol.qualified_name, function)

        return registry


def _load_implementation(root: Path, symbol: Any) -> Optional[Any]:
    """Import the realization an implementation declares."""
    source = symbol.metadata.get("source") or {}
    file = source.get("file")
    name = source.get("symbol")
    if not isinstance(file, str) or not isinstance(name, str):
        return None
    return _load_from_file(root, file, name)


def _load_module_function(root: Path, module: str, function: str) -> Optional[Any]:
    """Import a function of a module of the specification.

    The convention is a Python module of the same name in the project root.
    """
    for candidate in (root / f"{module}.py", root / module / f"{module}.py"):
        if candidate.is_file():
            return _load_from_file(root.parent, str(candidate.relative_to(root.parent)), function)
    return None


def _load_from_file(root: Path, file: str, name: str) -> Optional[Any]:
    path = (Path(root) / file).resolve()
    if not path.is_file():
        return None
    module_name = f"sdl_runtime_{path.stem}_{abs(hash(str(path))) % 100000}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return getattr(cached, name, None)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        return None
    return getattr(module, name, None)
