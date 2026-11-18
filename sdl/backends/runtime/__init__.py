"""The SDL runtime.

The runtime executes the flows of a canonical IR directly, without compiling
anything. It is what the `execute` mode of the specification asks for.

    from sdl.backends.runtime import Runtime

    runtime = Runtime.from_project(graph, project_root)
    runtime.register("PaymentProvider", my_provider)
    outputs = await runtime.run_flow("process_customer_payment", amount=10, ...)
"""

from sdl.backends.runtime.conditions import evaluate
from sdl.backends.runtime.errors import (
    FlowExecutionError,
    MandatoryOutputError,
    StepFailed,
    UnknownFlowError,
    UnknownTargetError,
)
from sdl.backends.runtime.interpreter import Runtime
from sdl.backends.runtime.registry import Registry
from sdl.backends.runtime.state import resolve_output, resolve_path

__all__ = [
    "FlowExecutionError",
    "MandatoryOutputError",
    "Registry",
    "Runtime",
    "StepFailed",
    "UnknownFlowError",
    "UnknownTargetError",
    "evaluate",
    "resolve_output",
    "resolve_path",
]
