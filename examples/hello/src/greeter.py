"""The realization of the SDL interface Greeter."""
from dataclasses import dataclass


@dataclass
class Greeting:
    """The Greeting type of the specification, in Python."""

    message: str


class Greeter:
    """Greets a person by name."""

    def greet(self, name: str) -> Greeting:
        """Greet the person with that name."""
        return Greeting(message=f"Hello, {name}!")
