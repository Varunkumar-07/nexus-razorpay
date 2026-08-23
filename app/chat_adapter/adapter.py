"""Chat Adapter (Phase 6) — the human-facing entry point.

Wraps the existing pipeline (recommend -> confirm -> gate -> order) as a
genuine two-turn conversation:
  Turn 1: buyer sends a request -> agent recommends and asks for explicit
          confirmation. If an upsell was offered alongside the primary
          product, the prompt offers three explicit options: accept both,
          accept the primary only, or cancel. If there's no upsell, it's
          the original two-way yes/no prompt, unchanged.
  Turn 2: buyer replies -> the Gate is only ever checked on an explicit,
          unambiguous reply (full bundle or primary-only) — never on a
          guess. Primary-only re-runs check_gate() against the smaller,
          correct amount (primary price x quantity only) before any order
          is created; it is not a shortcut around the Gate.

Every event this adapter generates is tagged source="chat" in the Audit Log.

A ChatSession holds state between turns (the pending recommendation and
its transaction_id) — one session per buyer conversation.
"""

from enum import Enum, auto
from typing import Optional

from app.gate.gate import check_gate
from app.razorpay_integration.orders import create_order
from app.reasoning.agent import recommend

SOURCE = "chat"

_AFFIRMATIVE = {
    "yes", "y", "yeah", "yep", "yup", "confirm", "confirmed", "sure", "ok", "okay",
    "please do", "do it", "go ahead", "place it", "place the order", "both",
    "yes both", "confirm both", "yes to both", "accept both",
}
_NEGATIVE = {"no", "n", "nope", "nah", "cancel", "don't", "dont", "stop", "never mind", "nevermind"}

# Phrases that unambiguously mean "accept the primary item, decline the
# upsell" — deliberately a small, explicit set (plus a couple of
# name-aware patterns below), not fuzzy guessing. Anything that doesn't
# clearly match one of these, or _AFFIRMATIVE, or _NEGATIVE, falls back to
# the clarifying re-ask — it is never treated as an approval.
_PRIMARY_ONLY_GENERIC_PHRASES = {
    "primary only", "just primary", "just the primary", "only primary",
    "only the primary", "primary", "just that one", "only that one",
    "without the upsell", "without upsell", "no upsell", "no thanks to the upsell",
    "skip the upsell", "skip upsell", "decline the upsell", "decline upsell",
    "not the upsell", "no to the upsell",
}


def _matches_primary_only(text: str, primary_name: str, upsell_name: Optional[str]) -> bool:
    """True if `text` unambiguously means "accept the primary item only".

    Recognizes a fixed generic phrase set, plus two name-aware patterns:
    "just/only the <primary product name>" and "without/no/not/skip the
    <upsell product name>". Deliberately conservative — anything that
    doesn't clearly match is left to the caller's clarifying re-ask rather
    than being guessed at.
    """
    normalized = text.strip().lower()

    if normalized in _PRIMARY_ONLY_GENERIC_PHRASES:
        return True

    primary_lower = primary_name.lower()
    if primary_lower in normalized and ("just" in normalized or "only" in normalized):
        return True

    if upsell_name:
        upsell_lower = upsell_name.lower()
        exclusion_phrases = (
            f"without the {upsell_lower}",
            f"without {upsell_lower}",
            f"no {upsell_lower}",
            f"not the {upsell_lower}",
            f"skip the {upsell_lower}",
            f"skip {upsell_lower}",
        )
        if any(phrase in normalized for phrase in exclusion_phrases):
            return True

    return False


class ChatState(Enum):
    AWAITING_REQUEST = auto()
    AWAITING_CONFIRMATION = auto()
    DONE = auto()


class ChatSession:
    """One buyer conversation through the Chat Adapter."""

    def __init__(self) -> None:
        self.state = ChatState.AWAITING_REQUEST
        self._pending: Optional[dict] = None
        self.last_transaction_id: Optional[str] = None

    def handle_message(self, text: str) -> str:
        """Handle one turn of buyer input and return the agent's reply."""
        if self.state == ChatState.AWAITING_CONFIRMATION:
            return self._handle_confirmation(text)
        return self._handle_request(text)

    def _handle_request(self, text: str) -> str:
        result = recommend(text, source=SOURCE)
        self.last_transaction_id = result["transaction_id"]

        if result["no_match"] or not result["primary"]:
            self.state = ChatState.DONE
            self._pending = None
            return result["reasoning"] or "Sorry, I couldn't find a good match for that request."

        primary = result["primary"]
        upsell = result["upsell"]
        # Quantity applies only to the primary product; the upsell (if any)
        # is always exactly one extra unit — never multiplied, never a
        # substitute for the primary's quantity.
        quantity = result["quantity"]

        primary_only_amount_paise = primary["price_paise"] * quantity
        amount_paise = primary_only_amount_paise
        if upsell:
            amount_paise += upsell["price_paise"]

        self._pending = {
            "transaction_id": result["transaction_id"],
            "amount_paise": amount_paise,  # full-bundle amount (what "yes" confirms)
            "primary_only_amount_paise": primary_only_amount_paise,
            "primary": primary,
            "upsell": upsell,
            "quantity": quantity,
            "reasoning": result["reasoning"],
        }
        self.state = ChatState.AWAITING_CONFIRMATION

        primary_label = f"{quantity}x {primary['name']}" if quantity > 1 else primary["name"]

        if quantity > 1:
            reply = (
                f"I'd recommend {quantity}x {primary['name']} "
                f"(Rs.{primary['price_paise'] / 100:.2f} each, "
                f"Rs.{primary_only_amount_paise / 100:.2f} total)."
            )
        else:
            reply = f"I'd recommend the {primary['name']} (Rs.{primary['price_paise'] / 100:.2f})."

        if upsell:
            reply += (
                f" You might also want the {upsell['name']} "
                f"(Rs.{upsell['price_paise'] / 100:.2f})."
            )
            reply += f" {result['reasoning']}"
            reply += (
                f" Confirm both items for Rs.{amount_paise / 100:.2f}? Reply 'yes' for both, "
                f"'primary only' for just the {primary_label} at Rs.{primary_only_amount_paise / 100:.2f}, "
                f"or 'no' to cancel."
            )
        else:
            reply += f" {result['reasoning']}"
            reply += f" Confirm order for Rs.{amount_paise / 100:.2f}?"

        return reply

    def _handle_confirmation(self, text: str) -> str:
        pending = self._pending
        normalized = text.strip().lower()
        has_upsell = pending["upsell"] is not None

        if normalized in _NEGATIVE:
            self.state = ChatState.DONE
            self._pending = None
            return "No problem — order cancelled. Let me know if you'd like to look at something else."

        if has_upsell and _matches_primary_only(text, pending["primary"]["name"], pending["upsell"]["name"]):
            return self._confirm(pending, primary_only=True)

        if normalized in _AFFIRMATIVE:
            return self._confirm(pending, primary_only=False)

        # Unclear reply: stay in AWAITING_CONFIRMATION and ask again.
        # Never default to approval (or to any specific path) on an
        # ambiguous response.
        if has_upsell:
            return (
                f"Sorry, I didn't catch that. Reply 'yes' to confirm both items for "
                f"Rs.{pending['amount_paise'] / 100:.2f}, 'primary only' for just the "
                f"{pending['primary']['name']} at Rs.{pending['primary_only_amount_paise'] / 100:.2f}, "
                f"or 'no' to cancel."
            )
        return (
            f"Sorry, I didn't catch that. Confirm order for "
            f"Rs.{pending['amount_paise'] / 100:.2f}? (yes/no)"
        )

    def _confirm(self, pending: dict, primary_only: bool) -> str:
        """Re-run the Gate against the correct amount for the chosen path,
        then create the order if approved. `primary_only` selects which of
        the two pre-computed amounts on `pending` is the TRUE amount being
        gated — the Gate is never skipped or approximated for either path.
        """
        amount_paise = pending["primary_only_amount_paise"] if primary_only else pending["amount_paise"]
        reasoning = pending["reasoning"]
        if primary_only:
            reasoning = (
                f"{reasoning} (Buyer declined the upsell; confirmed only the primary item: "
                f"{pending['primary']['name']}.)"
            )

        gate_result = check_gate(
            amount_paise=amount_paise,
            confirmed=True,
            reasoning=reasoning,
            transaction_id=pending["transaction_id"],
            source=SOURCE,
        )
        self.state = ChatState.DONE
        self._pending = None

        if not gate_result["approved"]:
            return f"I can't place that order: {gate_result['reason']}"

        order_result = create_order(gate_result, transaction_id=pending["transaction_id"], source=SOURCE)

        if not order_result["success"]:
            return f"Something went wrong placing the order: {order_result['error']}"

        order_id = order_result["order"]["id"]
        if primary_only:
            return f"Order placed. Order ID {order_id}. (Primary item only — the upsell was not included.)"
        return f"Order placed. Order ID {order_id}."
