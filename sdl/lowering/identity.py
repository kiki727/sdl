"""Deterministic identity for the canonical IR.

The identifier of a symbol must depend only on what the symbol *is*, never on
the order in which it was created or on a random source. Two builds of the
same document must therefore produce byte identical identifiers, which is what
makes the canonical IR reproducible.

The scheme is readable on purpose: a prefix says what kind of symbol it is,
the sanitised qualified name says which one it is, and a short digest keeps
two different symbols apart even when their names sanitise to the same text.
"""

from __future__ import annotations

import hashlib
import re

from sdl.ir.edges import EdgeId, EdgeKind
from sdl.ir.symbols import SymbolId

_UNSAFE = re.compile(r"[^A-Za-z0-9]+")


def sanitize(qualified_name: str) -> str:
    """Turn a qualified name into a fragment that is safe in an identifier."""
    return _UNSAFE.sub("_", qualified_name).strip("_") or "unnamed"


def digest(value: str, length: int = 8) -> str:
    """A short, stable digest of a string."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def symbol_id(prefix: str, qualified_name: str) -> SymbolId:
    """A stable identifier for a symbol."""
    return SymbolId(f"{prefix}_{sanitize(qualified_name)}_{digest(qualified_name)}")


def edge_id(kind: EdgeKind, source: str, target: str, index: int = 0) -> EdgeId:
    """A stable identifier for an edge.

    ``index`` distinguishes parallel edges of the same kind between the same
    pair of symbols.
    """
    payload = f"{kind.name}|{source}|{target}|{index}"
    return EdgeId(f"edge_{digest(payload, 12)}")
