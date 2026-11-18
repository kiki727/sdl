"""A provider that satisfies the contract of PaymentProvider."""
from decimal import Decimal

from types.payment_response import PaymentResponse


class GoodProvider:
    """Satisfies the SDL interface PaymentProvider."""

    def charge(self, amount: Decimal) -> PaymentResponse:
        return PaymentResponse(success=True, tx_id=None)
