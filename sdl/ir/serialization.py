"""Serialisation of the canonical IR.

The IR is serialised to JSON so that it can be inspected, diffed and compared.
Two properties matter:

* it is **deterministic**: symbols are ordered by qualified name, edges by
  kind and endpoints, and every mapping is written with sorted keys;
* it is **complete**: every field of every symbol survives the round trip, so
  two serialisations can be compared byte for byte.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from sdl.ir.edges import Edge
from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import (
    FlowStepSymbol,
    FlowSymbol,
    ImplementationSymbol,
    InterfaceSymbol,
    MethodSymbol,
    ProjectSymbol,
    Symbol,
    TypeSymbol,
)


def _plain(value: Any) -> Any:
    """Convert a value into something JSON can hold, deterministically."""
    if isinstance(value, dict):
        return {str(key): _plain(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if is_dataclass(value):
        return _plain(asdict(value))
    return str(value)


def symbol_to_dict(symbol: Symbol) -> dict[str, Any]:
    """The serialised form of a symbol."""
    data: dict[str, Any] = {
        "id": str(symbol.id),
        "kind": symbol.kind.name,
        "name": symbol.name,
        "qualified_name": symbol.qualified_name,
        "module_id": symbol.module_id,
        "metadata": _plain(symbol.metadata),
    }

    if isinstance(symbol, ProjectSymbol):
        data["version"] = symbol.version
    elif isinstance(symbol, InterfaceSymbol):
        data["version"] = symbol.version
        data["invariants"] = list(symbol.invariants)
    elif isinstance(symbol, ImplementationSymbol):
        data["version"] = symbol.version
        data["language"] = symbol.language
        data["implements"] = list(symbol.metadata.get("implements_list", []))
        data["source"] = {
            "file": symbol.source_file,
            "symbol": symbol.source_symbol,
        }
    elif isinstance(symbol, MethodSymbol):
        data["version"] = symbol.metadata.get("version", "")
        data["parameters"] = [
            {
                "name": parameter.name,
                "type_id": str(parameter.type_id),
                "optional": parameter.optional,
            }
            for parameter in symbol.parameters
        ]
        data["return_type_id"] = (
            str(symbol.return_type_id) if symbol.return_type_id else None
        )
    elif isinstance(symbol, TypeSymbol):
        data["type_kind"] = symbol.type_kind.name
        data["fields"] = [
            {"name": field.name, "type_id": str(field.type_id), "optional": field.optional}
            for field in symbol.fields
        ]
        data["constraints"] = list(symbol.constraints)
        if symbol.metadata.get("enum_values"):
            data["enum_values"] = list(symbol.metadata["enum_values"])
    elif isinstance(symbol, FlowSymbol):
        data["version"] = symbol.version
        data["state_definitions"] = {
            name: {
                "name": variable.name,
                "type_id": str(variable.type_id),
                "origin_step": str(variable.origin_step) if variable.origin_step else None,
            }
            for name, variable in sorted(symbol.state_definitions.items())
        }
        data["outputs"] = _plain(symbol.metadata.get("outputs", {}))
        data["output_mapping"] = _plain(symbol.metadata.get("output_mapping", {}))
        data["step_order"] = list(symbol.metadata.get("step_order", []))
    elif isinstance(symbol, FlowStepSymbol):
        data["call_target"] = symbol.metadata.get("call_target")
        data["mapping"] = _plain(symbol.metadata.get("mapping", {}))
        data["output_map"] = _plain(symbol.metadata.get("output_map", {}))
        data["condition"] = symbol.metadata.get("condition")
        data["on_error"] = symbol.metadata.get("on_error")
        data["retry"] = _plain(symbol.metadata.get("retry"))
        data["order"] = symbol.metadata.get("order", 0)

    return data


def edge_to_dict(edge: Edge) -> dict[str, Any]:
    """The serialised form of an edge."""
    return {
        "id": str(edge.id),
        "kind": edge.kind.name,
        "source": str(edge.source),
        "target": str(edge.target),
    }


def graph_to_dict(graph: SymbolGraph) -> dict[str, Any]:
    """The serialised form of a whole graph."""
    symbols = sorted(graph.symbols.values(), key=lambda item: item.qualified_name)
    edges = sorted(
        graph.edges.values(),
        key=lambda item: (item.kind.name, str(item.source), str(item.target)),
    )
    return {
        "symbols": [symbol_to_dict(symbol) for symbol in symbols],
        "edges": [edge_to_dict(edge) for edge in edges],
    }


def dumps(graph: SymbolGraph) -> str:
    """The canonical JSON text of a graph."""
    return json.dumps(graph_to_dict(graph), indent=2, sort_keys=True, ensure_ascii=False)


def dump(graph: SymbolGraph, path: Path) -> None:
    """Write the canonical JSON text of a graph to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(graph) + "\n", encoding="utf-8")
