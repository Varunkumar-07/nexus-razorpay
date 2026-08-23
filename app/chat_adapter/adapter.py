"""Chat Adapter (Phase 6) — the human-facing entry point.

Wraps the existing pipeline (recommend -> confirm -> gate -> order) as a
genuine two-turn conversation:
  Turn 1: buyer sends a request -> agent recommends and asks
          "Confirm order for Rs.X?"
  Turn 2: buyer replies -> only on an explicit "yes" is the Gate checked
          with confirmed=True, and only if the Gate approves does an order
          get created.

Every event this adapter generates is tagged source="chat" in the Audit Log.

A ChatSession holds state between the two turns (the pending recommendation
and its transaction_id) — one session per buyer conversation.
"""

from enum import Enum, auto
from typing import Optional

from app.gate.gate import check_gate
from app.razorpay_integration.orders import create_order
from app.reasoning.agent import recommend

SOURCE = "chat"

_AFFIRMATIVE = {
    "yes", "y", "yeah", "yep", "yup", "confirm", "confirmed", "sure", "ok", "okay",
    "please do", "do it", "go ahead", "place it", "place the order",
}
_NEGATIVE = {"no", "n", "nope", "nah", "cancel", "don't", "dont", "stop", "never mind", "nevermind"}


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

        amount_paise = result["primary"]["price_paise"]
        if result["upsell"]:
            amount_paise += result["upsell"]["price_paise"]

        self._pending = {
            "transaction_id": result["transaction_id"],
            "amount_paise": amount_paise,
            "reasoning": result["reasoning"],
        }
        self.state = ChatState.AWAITING_CONFIRMATION

        reply = (
            f"I'd recommend the {result['primary']['name']} "
            f"(Rs.{result['primary']['price_paise'] / 100:.2f})."
        )
        if result["upsell"]:
            reply += (
                f" You might also want the {result['upsell']['name']} "
                f"(Rs.{result['upsell']['price_paise'] / 100:.2f})."
            )
        reply += f" {result['reasoning']}"
        reply += f" Confirm order for Rs.{amount_paise / 100:.2f}?"
        return reply

    def _handle_confirmation(self, text: str) -> str:
        pending = self._pending
        normalized = text.strip().lower()

        if normalized in _NEGATIVE:
            self.state = ChatState.DONE
            self._pending = None
            return "No problem — order cancelled. Let me know if you'd like to look at something else."

        if normalized not in _AFFIRMATIVE:
            # Unclear reply: stay in AWAITING_CONFIRMATION and ask again.
            # Never default to approval on an ambiguous response.
            return (
                f"Sorry, I didn't catch that. Confirm order for "
                f"Rs.{pending['amount_paise'] / 100:.2f}? (yes/no)"
            )

        gate_result = check_gate(
            amount_paise=pending["amount_paise"],
            confirmed=True,
            reasoning=pending["reasoning"],
            transaction_id=pending["transaction_id"],
            source=SOURCE,
        )
        self.state = ChatState.DONE

        if not gate_result["approved"]:
            self._pending = None
            return f"I can't place that order: {gate_result['reason']}"

        order_result = create_order(
            gate_result, transaction_id=pending["transaction_id"], source=SOURCE
        )
        self._pending = None

        if not order_result["success"]:
            return f"Something went wrong placing the order: {order_result['error']}"

        return f"Order placed. Order ID {order_result['order']['id']}."
