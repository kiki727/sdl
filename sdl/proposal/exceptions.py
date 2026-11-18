"""The exceptions of the proposal protocol."""

from sdl.diagnostics import Report


class ProposalError(Exception):
    """Base class for all proposal related errors."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class StaleProposalError(ProposalError):
    """The proposal is based on an older version of the specification."""

    def __init__(self, base_version: str, current_version: str):
        super().__init__(
            f"Proposal version {base_version} is stale. "
            f"Current version is {current_version}."
        )
        self.base_version = base_version
        self.current_version = current_version


class PatchConflictError(ProposalError):
    """Two patches of the same proposal target the same element."""


class PatchApplicationError(ProposalError):
    """A patch could not be applied."""


class ValidationFailedError(ProposalError):
    """The proposal failed one of the validation phases."""

    def __init__(self, phase: str, report: Report | None = None):
        count = len(report.errors) if report is not None else 0
        super().__init__(f"Proposal failed the {phase} phase with {count} error(s).")
        self.phase = phase
        self.report = report
