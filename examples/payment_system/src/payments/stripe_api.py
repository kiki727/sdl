"""The realization of the SDL interface ``PaymentProvider``.

The runtime imports this file directly, with no package context, so the types
of the specification are defined here. The validator reads the same
annotations and checks them against the interface.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4


@dataclass
class PaymentRequest:
    """The ``PaymentRequest`` type of the specification, in Python."""

    amount: Decimal
    currency: str
    payment_method_token: str


@dataclass
class PaymentResponse:
    """The ``PaymentResponse`` type of the specification, in Python."""

    success: bool
    tx_id: UUID
    timestamp: datetime


class StripePaymentProvider:
    """Satisfies the SDL interface ``PaymentProvider``."""

    def charge(self, request: PaymentRequest) -> PaymentResponse:
        """Charge the request and report the transaction."""
        if request.amount <= 0:
            return PaymentResponse(
                success=False,
                tx_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
            )
        return PaymentResponse(
            success=True,
            tx_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
        )
