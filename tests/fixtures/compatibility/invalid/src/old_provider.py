"""A provider of an older version than the contract asks for."""
from decimal import Decimal

from types.payment_response import PaymentResponse


class OldProvider:
    """Satisfies the contract, but at the wrong version."""

    def charge(self, amount: Decimal) -> PaymentResponse:
        return PaymentResponse(success=True, tx_id=None)
