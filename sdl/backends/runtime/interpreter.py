"""The SDL runtime.

Specification section 7.1: in the `execute` mode the runtime *directly
executes flows and calls implementations via dynamic binding*. Nothing is
compiled. The runtime reads the canonical IR and runs it.

The execution of a flow follows the specification exactly:

* the steps run in the order they are defined (section 3.1);
* a step whose condition is false is skipped (section 3.2);
* the data of a step moves only through the explicit mappings (section 2.3);
* the error strategy of a step decides what happens when it fails
  (section 3.3.1);
* the outputs of a flow are populated from the Flow State, and a mandatory
  output that cannot be populated fails the flow (section 3.3.2).
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from sdl.backends.runtime.conditions import evaluate
from sdl.backends.runtime.errors import (
    MandatoryOutputError,
    StepFailed,
    UnknownFlowError,
    UnknownTargetError,
)
from sdl.backends.runtime.registry import Registry
from sdl.backends.runtime.state import resolve_output, resolve_path
from sdl.ir.graph import SymbolGraph
from sdl.ir.symbols import FlowStepSymbol, FlowSymbol, InterfaceSymbol, SymbolId


class Runtime:
    """Executes the flows of a canonical IR."""

    def __init__(self, graph: SymbolGraph, registry: Optional[Registry] = None):
        self.graph = graph
        self.registry = registry if registry is not None else Registry()

    # -- registry ------------------------------------------------------------

    def register(self, name: str, implementation: Any) -> None:
        """Register an implementation for a name."""
        self.registry.register(name, implementation)

    @classmethod
    def from_project(cls, graph: SymbolGraph, root: Path) -> "Runtime":
        """Build a runtime for a project, with the registry of its bindings."""
        return cls(graph, Registry.from_project(graph, Path(root)))

    # -- flows ---------------------------------------------------------------

    def flow(self, flow_id: str, /) -> FlowSymbol:
        """The flow of a name.

        The parameter is positional only, so that a flow may declare an input
        called `flow_id`.
        """
        symbol_id = self.graph.resolve_symbol(flow_id)
        symbol = self.graph.get_symbol(symbol_id) if symbol_id else None
        if not isinstance(symbol, FlowSymbol):
            raise UnknownFlowError(f"The project has no flow named {flow_id!r}.")
        return symbol

    def flows(self) -> List[FlowSymbol]:
        """Every flow of the project, in order."""
        return sorted(
            (
                symbol
                for symbol in self.graph.symbols.values()
                if isinstance(symbol, FlowSymbol)
            ),
            key=lambda item: item.name,
        )

    async def run_flow(self, flow_id: str, /, **inputs: Any) -> Dict[str, Any]:
        """Run a flow and return its outputs.

        The name of the flow is positional only, so that a flow may declare
        an input called `flow_id`.
        """
        flow = self.flow(flow_id)
        declared = set(flow.metadata.get("inputs", {}))
        missing = declared - set(inputs)
        if missing:
            raise TypeError(
                f"The flow {flow_id!r} needs the input(s) "
                f"{', '.join(sorted(missing))}."
            )

        state: Dict[str, Any] = dict(inputs)
        steps = self._steps_of(flow)
        index = 0

        while index < len(steps):
            step = steps[index]
            condition = step.metadata.get("condition")

            if condition:
                if not evaluate(condition, state):
                    index += 1
                    continue

            try:
                result = await self._call(step, state)
            except UnknownTargetError:
                # A target that is not registered is a mistake in the
                # configuration, not a failure of the step.
                raise
            except Exception as error:
                index = self._handle_error(flow, step, steps, index, error)
                continue

            for variable, path in (step.metadata.get("output_map") or {}).items():
                state[variable] = resolve_output(result, path)

            index += 1

        return self._outputs(flow, state)

    # -- the steps -----------------------------------------------------------

    def _steps_of(self, flow: FlowSymbol) -> List[FlowStepSymbol]:
        steps = []
        for step_id in flow.metadata.get("step_order", []):
            symbol = self.graph.get_symbol(step_id)
            if isinstance(symbol, FlowStepSymbol):
                steps.append(symbol)
        return steps

    async def _call(self, step: FlowStepSymbol, state: Mapping[str, Any]) -> Any:
        """Call the target of a step."""
        target = str(step.metadata.get("call_target", ""))
        mapping = step.metadata.get("mapping") or {}
        arguments = {
            parameter: resolve_path(state, path) for parameter, path in mapping.items()
        }

        on_error = step.metadata.get("on_error") or "fail"
        if on_error == "retry":
            retry = step.metadata.get("retry") or {}
            return await self._call_with_retry(
                target,
                arguments,
                attempts=int(retry.get("attempts", 1) or 1),
                backoff=str(retry.get("backoff") or "fixed"),
                initial_interval=_seconds(retry.get("initial_interval")),
                max_interval=_seconds(retry.get("max_interval")),
            )

        implementation = self._resolve_target(target)
        result = implementation(**arguments)
        if inspect.isawaitable(result):
            result = await result
        return result

    def _resolve_target(self, target: str) -> Any:
        """The callable a target names.

        Specification section 6.2: when a module calls a method of an
        interface, the runtime uses the bindings table to determine which
        concrete code to execute. So ``Checker::check`` is resolved to the
        method of the implementation the project bound to ``Checker``.
        """
        if target in self.registry:
            return self.registry.resolve(target)

        if "::" in target:
            owner, _, member = target.partition("::")
            owner_id = self.graph.resolve_symbol(owner)
            owner_symbol = self.graph.get_symbol(owner_id) if owner_id else None
            if isinstance(owner_symbol, InterfaceSymbol) and owner in self.registry:
                implementation = self.registry.resolve(owner)
                method = getattr(implementation, member, None)
                if method is not None:
                    return method

        return self.registry.resolve(target)

    async def _call_with_retry(
        self,
        target: str,
        arguments: Dict[str, Any],
        *,
        attempts: int,
        backoff: str,
        initial_interval: float,
        max_interval: float,
    ) -> Any:
        """Call a target, repeating it according to the retry policy."""
        delay = initial_interval
        failure: Any = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                implementation = self._resolve_target(target)
                result = implementation(**arguments)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as error:  # noqa: BLE001 - the policy decides
                failure = error
                if attempt >= attempts:
                    break
                if delay > 0:
                    await asyncio.sleep(delay)
                if backoff == "exponential":
                    delay = min(delay * 2, max_interval)
                elif backoff == "linear":
                    delay = min(delay + initial_interval, max_interval)
        raise StepFailed(
            f"The step calling {target!r} failed after {attempts} attempt(s): {failure}"
        ) from failure

    def _handle_error(
        self,
        flow: FlowSymbol,
        step: FlowStepSymbol,
        steps: List[FlowStepSymbol],
        index: int,
        error: Exception,
    ) -> int:
        """Apply the error strategy of a step and return the next index."""
        on_error = step.metadata.get("on_error") or "fail"

        if on_error == "ignore":
            return index + 1

        if on_error.startswith("goto "):
            target = on_error[5:].strip()
            for position, candidate in enumerate(steps):
                if candidate.name == target:
                    return position
            raise StepFailed(
                f"The step {step.name!r} wants to go to {target!r}, which is not a "
                f"step of the flow."
            ) from error

        raise StepFailed(
            f"The step {step.name!r} of the flow {flow.name!r} failed: {error}"
        ) from error

    # -- the outputs ---------------------------------------------------------

    def _outputs(self, flow: FlowSymbol, state: Mapping[str, Any]) -> Dict[str, Any]:
        """The outputs of a flow, and the check of the mandatory ones."""
        outputs = flow.metadata.get("outputs", {})
        mapping = flow.metadata.get("output_mapping", {})

        result: Dict[str, Any] = {}
        for name in sorted(outputs):
            path = mapping.get(name)
            if path is None:
                raise MandatoryOutputError(name, dict(state))
            try:
                result[name] = resolve_path(state, path)
            except Exception as error:
                raise MandatoryOutputError(name, dict(state)) from error
        return result


def _seconds(value: Any) -> float:
    """A duration of the specification, in seconds."""
    if not isinstance(value, str):
        return 1.0
    digits = value.rstrip("ms")
    try:
        number = float(digits)
    except ValueError:
        return 1.0
    if value.endswith("ms"):
        return number / 1000.0
    if value.endswith("m"):
        return number * 60.0
    return number


__all__ = ["Runtime", "UnknownFlowError", "UnknownTargetError"]
