"""A provider that does not accept what the contract asks for."""
from decimal import Decimal

from types.payment_response import PaymentResponse


class NarrowProvider:
    """Accepts a String where the contract asks for a Decimal."""

    def charge(self, amount: str) -> PaymentResponse:
        return PaymentResponse(success=True, tx_id=None)
