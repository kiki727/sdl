"""Reading the Flow State and the output of a step.

Specification section 2.3 defines how data moves:

* an **input mapping** reads a path of the Flow State and binds it to a
  parameter of the called method;
* an **output mapping** binds the whole output of the method, or one of its
  fields, to a variable of the Flow State.

A path is a dotted name. The first segment names a variable of the state, the
others name a field of it. A field is read from a mapping by its key and from
an object by its attribute.
"""

from __future__ import annotations

from typing import Any, Mapping

#: The name the specification gives to the whole output of a method.
RESULT = "result"


class StateError(Exception):
    """A path that does not exist in the state."""


def resolve_path(state: Mapping[str, Any], path: str) -> Any:
    """Read a path of the Flow State."""
    parts = str(path).split(".")
    current: Any = state
    for index, part in enumerate(parts):
        if isinstance(current, Mapping):
            if part not in current:
                raise StateError(
                    f"The state variable {parts[0]!r} has no field {part!r}."
                    if index
                    else f"The state has no variable {part!r}."
                )
            current = current[part]
            continue
        if hasattr(current, part):
            current = getattr(current, part)
            continue
        raise StateError(
            f"The value of {parts[0]!r} has no field {part!r}."
            if index
            else f"The state has no variable {part!r}."
        )
    return current


def resolve_output(result: Any, path: str) -> Any:
    """Read the value an output mapping binds into the state.

    ``result`` is the whole output of the method. Anything else is a path
    into it, with the leading ``result`` naming the output itself.
    """
    parts = str(path).split(".")
    if parts[0] == RESULT:
        parts = parts[1:]
        if not parts:
            return result
        current = result
        for part in parts:
            if isinstance(current, Mapping):
                if part not in current:
                    raise StateError(f"The output has no field {part!r}.")
                current = current[part]
                continue
            if hasattr(current, part):
                current = getattr(current, part)
                continue
            raise StateError(f"The output has no field {part!r}.")
    return resolve_path({"result": result}, path)
