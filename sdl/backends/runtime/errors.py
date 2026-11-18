"""The errors the SDL runtime raises."""

from typing import Any


class FlowExecutionError(Exception):
    """The base class of every error of the runtime."""


class UnknownTargetError(FlowExecutionError):
    """A step names something that is not registered."""


class StepFailed(FlowExecutionError):
    """A step failed and its error strategy does not recover from it."""


class MandatoryOutputError(FlowExecutionError):
    """A mandatory output of a flow could not be populated."""

    def __init__(self, name: str, state: Any = None):
        super().__init__(f"The mandatory output {name!r} could not be populated.")
        self.name = name
        self.state = state


class UnknownFlowError(FlowExecutionError):
    """The runtime was asked for a flow that does not exist."""
