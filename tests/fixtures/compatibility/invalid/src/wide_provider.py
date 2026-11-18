"""A provider that returns something the contract does not allow."""
from decimal import Decimal


class WideProvider:
    """Returns a String where the contract asks for a PaymentResponse."""

    def charge(self, amount: Decimal) -> str:
        return "paid"
