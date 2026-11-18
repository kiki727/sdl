"""The data model of a proposal.

Specification section 8.2 defines the envelope of a proposal and section 8.3
the semantics of a patch.

    proposal:
      id: prop_pay_v2_migration
      target_version: "1.0.0"
      author: "agent-gemma4"
      rationale: "Migration to PaymentProvider v2."
      patches:
        - target: "project.bindings[PaymentProvider]"
          action: replace
          value:
            interface: PaymentProvider
            version: "2.0.0"
            implementation: stripe_v2_provider
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List


class PatchAction(Enum):
    """The action of a patch. Specification section 8.3."""

    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"

    @classmethod
    def from_string(cls, value: Any) -> "PatchAction":
        if isinstance(value, PatchAction):
            return value
        if isinstance(value, str):
            for action in cls:
                if action.value == value:
                    return action
        raise ValueError(f"Unknown patch action {value!r}.")


@dataclass
class Patch:
    """One patch of a proposal."""

    target: str
    action: PatchAction = PatchAction.REPLACE
    value: Any = None


@dataclass
class Proposal:
    """A formal request for change."""

    id: str = "unknown"
    target_version: str = "0.0.0"
    author: str = "unknown"
    rationale: str = ""
    patches: List[Patch] = field(default_factory=list)
    approve: bool = False
