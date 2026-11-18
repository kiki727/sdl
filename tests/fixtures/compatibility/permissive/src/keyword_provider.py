"""A provider that accepts keyword arguments through ``**kwargs``."""

from decimal import Decimal

from types.payment_response import PaymentResponse


class KeywordProvider:
    """Accepts every keyword the contract sends."""

    def charge(self, amount: Decimal, **kwargs: object) -> PaymentResponse:
        return PaymentResponse(success=True, tx_id=None)
