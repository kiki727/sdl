"""A provider whose signature cannot be verified.

It declares neither the parameter type nor the return type, so the validator
must report ``SDL-E607`` instead of silently accepting the signature.
"""


class UnannotatedProvider:
    """Satisfies nothing the validator can check."""

    def charge(self, amount):
        return amount
