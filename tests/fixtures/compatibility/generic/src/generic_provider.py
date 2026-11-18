"""A provider whose signature keeps the arguments of the generic Result."""

from decimal import Decimal

from types.error import Error
from types.payment_response import PaymentResponse


class GenericProvider:
    """Satisfies a contract that returns ``Result<PaymentResponse, Error>``."""

    def charge(self, amount: Decimal) -> Result[PaymentResponse, Error]:
        return Result(value=PaymentResponse(success=True, tx_id=None))
