"""The Gate (Phase 3).

Sits between "the agent has a recommendation" and "an order gets created."
Every order must pass three checks before Phase 5 is allowed to call
Razorpay:
  1. Amount bound — total must not exceed AUTO_APPROVAL_LIMIT_PAISE.
  2. Explicit confirmation — the buyer/agent must have confirmed.
  3. Reasoning present — a non-empty explanation of why this recommendation
     was made, so the eventual Audit Log (Phase 4) has something meaningful
     to record.

This module does NOT call Razorpay and does NOT create orders. It only
decides pass/fail.
"""

from dataclasses import dataclass
from typing import Optional

# Named so it can be referenced directly (docs, pitch video) instead of a
# magic number buried in logic.
AUTO_APPROVAL_LIMIT_PAISE = 500_000  # Rs. 5,000


@dataclass(frozen=True)
class GateResult:
    approved: bool
    reason: Optional[str] = None
    amount_paise: Optional[int] = None
    confirmed: Optional[bool] = None
    reasoning: Optional[str] = None

    def to_dict(self) -> dict:
        if self.approved:
            return {
                "approved": True,
                "amount_paise": self.amount_paise,
                "confirmed": self.confirmed,
                "reasoning": self.reasoning,
            }
        return {"approved": False, "reason": self.reason}


def check_gate(amount_paise: int, confirmed: bool, reasoning: str) -> dict:
    """Run the three gate checks against a proposed order.

    Checks are evaluated in order (amount, then confirmation, then
    reasoning) and the first failing check determines the rejection reason.

    Args:
        amount_paise: total order value, in paise.
        confirmed: whether the buyer/agent explicitly confirmed this order.
        reasoning: the reasoning string behind this recommendation; must be
            non-empty for the gate to pass.

    Returns:
        {"approved": True, "amount_paise": ..., "confirmed": ..., "reasoning": ...}
        or
        {"approved": False, "reason": "<human-readable reason>"}
    """
    if amount_paise > AUTO_APPROVAL_LIMIT_PAISE:
        return GateResult(
            approved=False,
            reason=(
                f"Amount Rs.{amount_paise / 100:,.2f} exceeds "
                f"Rs.{AUTO_APPROVAL_LIMIT_PAISE / 100:,.2f} auto-approval limit."
            ),
        ).to_dict()

    if not confirmed:
        return GateResult(
            approved=False,
            reason="Order was not explicitly confirmed by the buyer/agent.",
        ).to_dict()

    if not reasoning or not reasoning.strip():
        return GateResult(
            approved=False,
            reason="No reasoning provided for this recommendation.",
        ).to_dict()

    return GateResult(
        approved=True,
        amount_paise=amount_paise,
        confirmed=confirmed,
        reasoning=reasoning,
    ).to_dict()
