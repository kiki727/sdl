"""A provider that accepts more than the contract asks for.

Specification section 5.2, input contravariance: the input of the contract
must be assignable to the input the implementation accepts. An
implementation that accepts ``Optional[str]`` accepts every ``str`` the
contract can send, so it satisfies the contract.
"""
from decimal import Decimal
from typing import Optional

from types.payment_response import PaymentResponse


class WideProvider:
    """Accepts more than the contract asks for."""

    def charge(self, amount: Optional[Decimal]) -> PaymentResponse:
        """Charge the amount, or nothing at all."""
        if amount is None:
            return PaymentResponse(success=False, tx_id=None)
        return PaymentResponse(success=True, tx_id=None)
