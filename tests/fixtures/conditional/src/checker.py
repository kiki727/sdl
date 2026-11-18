"""The realization of the SDL interface Checker."""


class Check:
    """The Check type of the fixture."""

    def __init__(self, is_valid: bool = True, token: str = "token") -> None:
        self.is_valid = is_valid
        self.token = token


class Checker:
    """Checks a value."""

    def check(self, value: str) -> Check:
        """Check the value and report whether it is valid."""
        return Check(is_valid=bool(value))
