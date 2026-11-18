"""Version ranges, as Core 0.2 section 4.5 defines them.

A requirement is a list of comparators separated by spaces. A version
satisfies a requirement when it satisfies every comparator of it.

    "1.0.0"        exactly that version
    "^1.0.0"       compatible with that version, below the next major
    "~1.0.0"       compatible with that version, below the next minor
    ">=1.0.0"      at least that version
    "<2.0.0"       below that version
    ">=1.0.0 <2.0.0"  both
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_COMPARATOR = re.compile(r"^(>=|<=|>|<|=|==|\^|~)?\s*(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    """A version as a triple of numbers."""
    match = _VERSION.match(str(text).strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _compare(left: Tuple[int, int, int], right: Tuple[int, int, int]) -> int:
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def _satisfies_one(version: Tuple[int, int, int], comparator: str) -> bool:
    match = _COMPARATOR.match(comparator.strip())
    if not match:
        # A requirement that cannot be read is not satisfied.
        return False

    operator = match.group(1) or "="
    major, minor, patch = int(match.group(2)), int(match.group(3)), int(match.group(4))
    other = (major, minor, patch)
    order = _compare(version, other)

    if operator in ("=", "=="):
        return order == 0
    if operator == ">=":
        return order >= 0
    if operator == ">":
        return order > 0
    if operator == "<=":
        return order <= 0
    if operator == "<":
        return order < 0
    if operator == "^":
        # Below the next major version, or the next minor when the major is 0.
        if major > 0:
            ceiling = (major + 1, 0, 0)
        elif minor > 0:
            ceiling = (0, minor + 1, 0)
        else:
            ceiling = (0, 0, patch + 1)
        return order >= 0 and _compare(version, ceiling) < 0
    if operator == "~":
        ceiling = (major, minor + 1, 0)
        return order >= 0 and _compare(version, ceiling) < 0

    return False


def satisfies(version: str, requirement: str) -> bool:
    """Whether a version satisfies a requirement."""
    parsed = parse_version(version)
    if parsed is None:
        return False
    comparators = [part for part in str(requirement).split(" ") if part]
    if not comparators:
        return False
    return all(_satisfies_one(parsed, comparator) for comparator in comparators)
