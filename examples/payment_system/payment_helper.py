"""The realization of the SDL module ``payment_helper``.

The runtime loads a module function from a Python module of the same name in
the project root. The module has no package context, so the types it returns
are defined here rather than imported from the generated package.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class PaymentRequest:
    """The ``PaymentRequest`` type of the specification, in Python."""

    amount: Decimal
    currency: str
    payment_method_token: str


def build_request(amount: Decimal, token: str) -> PaymentRequest:
    """Build the request an implementation of ``PaymentProvider`` accepts."""
    return PaymentRequest(
        amount=amount,
        currency="USD",
        payment_method_token=token,
    )
