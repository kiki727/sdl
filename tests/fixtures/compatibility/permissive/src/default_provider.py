"""A provider with a default value.

A default value does not widen the declared type: ``amount`` still accepts a
``Decimal``, and the extra parameter is simply optional.
"""

from decimal import Decimal

from types.payment_response import PaymentResponse


class DefaultProvider:
    """Accepts an extra optional parameter."""

    def charge(
        self, amount: Decimal, note: str = "ok"
    ) -> PaymentResponse:
        return PaymentResponse(success=True, tx_id=None)
