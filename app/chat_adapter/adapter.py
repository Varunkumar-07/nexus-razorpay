"""Chat Adapter (Phase 6) — the human-facing entry point.

Wraps the existing pipeline (recommend -> confirm -> gate -> order) as a
genuine multi-turn conversation:
  Turn 1: buyer sends a request -> agent recommends. If the request didn't
          explicitly state a quantity for the primary product, NEXUS first
          asks how many (AWAITING_QUANTITY) before presenting any price. If
          a quantity was explicitly stated, this step is skipped entirely.
  Turn 2: once quantity is settled, NEXUS asks for explicit confirmation.
          If an upsell was offered alongside the primary product, the
          prompt offers three explicit options: accept both, accept the
          primary only, or cancel. If there's no upsell, it's the original
          two-way yes/no prompt, unchanged.
  Turn 3: buyer replies -> the Gate is only ever checked on an explicit,
          unambiguous reply (full bundle or primary-only) — never on a
          guess. Primary-only re-runs check_gate() against the smaller,
          correct amount (primary price x quantity only) before any order
          is created; it is not a shortcut around the Gate.
  After any terminal outcome of that order attempt (order placed, in full
          or primary-only, a Gate rejection, an order-creation failure, or
          an explicit decline), NEXUS asks whether the buyer wants to look
          at anything else (AWAITING_CONTINUE_SHOPPING). A clear "yes" (or
          a message that's itself a new product request) starts a
          completely fresh recommend() cycle — its own transaction_id, its
          own quantity/confirmation/Gate/order steps, its own audit trail —
          exactly like a brand new session. A clear "no" ends the
          conversation. Nothing here ever bundles two products into one
          order or one Gate check.

Every event this adapter generates is tagged source="chat" in the Audit Log.

A ChatSession holds state between turns (the pending recommendation and
its transaction_id) — one session per buyer conversation.
"""

import re
from enum import Enum, auto
from typing import Optional

from app.audit.audit_log import log_event
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


_QUANTITY_WORD_VALUES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _parse_quantity_reply(text: str) -> Optional[int]:
    """Parse a buyer's answer to "How many would you like?".

    Accepts a bare digit ("2"), a digit embedded in simple phrasing
    ("2 please", "just 2"), or a small number word ("two", "just one",
    "two please"). Returns None on anything else (including "0" or a
    negative number) — the caller re-asks rather than guessing at a
    quantity.
    """
    normalized = text.strip().lower()

    digit_match = re.search(r"\d+", normalized)
    if digit_match:
        value = int(digit_match.group())
        return value if value >= 1 else None

    for word, value in _QUANTITY_WORD_VALUES.items():
        if re.search(rf"\b{word}\b", normalized):
            return value

    return None


# Small, fixed set of non-answers to "Would you like to look at anything
# else?" — deliberately narrow, same discipline as every other confirmation
# state in this system. Anything NOT in this set and NOT a recognized
# yes/no is treated as a direct new product request (an implicit "yes"),
# because that is exactly what AWAITING_REQUEST already does with any text
# it's handed — including gracefully no-matching genuine gibberish.
_CONTINUE_SHOPPING_UNCLEAR_PHRASES = {
    "maybe", "not sure", "maybe later", "maybe later idk", "maybe, not sure",
    "idk", "i don't know", "i dont know", "later", "hmm", "meh", "unsure",
}

# Ways of declining "Would you like to look at anything else?" that are NOT
# an order for a product literally called "nothing"/"that's all" — this is
# a superset of the general _NEGATIVE set, scoped to this one state, because
# a buyer here is answering a specific closing question, not a yes/no on an
# order. Without this, "Nothing" (a real bug: see FAILURE_LOG.md Entry 10)
# fell through to the implicit-new-request branch below, which called
# recommend("Nothing"), no-matched, and silently ended the session in a way
# indistinguishable from a fresh/finished one — instead of a clean decline.
_CONTINUE_SHOPPING_NEGATIVE_PHRASES = _NEGATIVE | {
    "nothing", "nothing else", "nothing more", "not really", "nah, that's all",
    "that's all", "thats all", "that's it", "thats it", "that'll be all",
    "thats all for now", "i'm done", "im done", "i am done", "i'm good",
    "im good", "no thanks", "no thank you", "bye", "goodbye", "good bye",
    "done", "all done",
}

_AFFIRMATIVE_PREFIXES = ("yes,", "yes ", "yeah,", "yeah ", "sure,", "sure ", "yep,", "yep ", "ok,", "ok ")


def _strip_leading_affirmative(text: str) -> str:
    """Strip a leading "yes,"/"sure," etc. from an implicit-yes reply like
    "yes, show me tents" before handing the rest to recommend() as the new
    product request — so the affirmative doesn't confuse catalog matching.
    """
    stripped = text.strip()
    lowered = stripped.lower()
    for prefix in _AFFIRMATIVE_PREFIXES:
        if lowered.startswith(prefix):
            return stripped[len(prefix):].strip(" ,")
    return stripped


class ChatState(Enum):
    AWAITING_REQUEST = auto()
    AWAITING_QUANTITY = auto()
    AWAITING_CONFIRMATION = auto()
    AWAITING_CONTINUE_SHOPPING = auto()
    DONE = auto()


class ChatSession:
    """One buyer conversation through the Chat Adapter."""

    def __init__(self) -> None:
        self.state = ChatState.AWAITING_REQUEST
        self._pending: Optional[dict] = None
        self.last_transaction_id: Optional[str] = None

    def handle_message(self, text: str) -> str:
        """Handle one turn of buyer input and return the agent's reply."""
        if self.state == ChatState.AWAITING_QUANTITY:
            return self._handle_quantity(text)
        if self.state == ChatState.AWAITING_CONFIRMATION:
            return self._handle_confirmation(text)
        if self.state == ChatState.AWAITING_CONTINUE_SHOPPING:
            return self._handle_continue_shopping(text)
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

        if not result["quantity_explicit"]:
            # The buyer didn't state a quantity — ask before presenting any
            # price, instead of silently defaulting to 1. Only the pieces
            # that don't depend on quantity are known yet.
            self._pending = {
                "transaction_id": result["transaction_id"],
                "primary": primary,
                "upsell": upsell,
                "reasoning": result["reasoning"],
            }
            self.state = ChatState.AWAITING_QUANTITY
            return f"How many would you like? (Recommended: {primary['name']}.)"

        return self._finalize_pending(
            transaction_id=result["transaction_id"],
            primary=primary,
            upsell=upsell,
            quantity=result["quantity"],
            reasoning=result["reasoning"],
        )

    def _handle_quantity(self, text: str) -> str:
        pending = self._pending
        quantity = _parse_quantity_reply(text)

        if quantity is None:
            log_event(
                transaction_id=pending["transaction_id"],
                source=SOURCE,
                event_type="quantity_unclear",
                details={"buyer_input": text},
            )
            return "Sorry, I didn't catch a quantity. How many would you like? (e.g. '1', '2', 'two')"

        return self._finalize_pending(
            transaction_id=pending["transaction_id"],
            primary=pending["primary"],
            upsell=pending["upsell"],
            quantity=quantity,
            reasoning=pending["reasoning"],
        )

    def _finalize_pending(
        self, transaction_id: str, primary: dict, upsell: Optional[dict], quantity: int, reasoning: str
    ) -> str:
        """Now that quantity is known (explicit in the original request, or
        just answered), compute the real amounts and move to confirmation.
        """
        # Quantity applies only to the primary product; the upsell (if any)
        # is always exactly one extra unit — never multiplied, never a
        # substitute for the primary's quantity.
        primary_only_amount_paise = primary["price_paise"] * quantity
        amount_paise = primary_only_amount_paise
        if upsell:
            amount_paise += upsell["price_paise"]

        self._pending = {
            "transaction_id": transaction_id,
            "amount_paise": amount_paise,  # full-bundle amount (what "yes" confirms)
            "primary_only_amount_paise": primary_only_amount_paise,
            "primary": primary,
            "upsell": upsell,
            "quantity": quantity,
            "reasoning": reasoning,
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
            reply += f" {reasoning}"
            reply += (
                f" Confirm both items for Rs.{amount_paise / 100:.2f}? Reply 'yes' for both, "
                f"'primary only' for just the {primary_label} at Rs.{primary_only_amount_paise / 100:.2f}, "
                f"or 'no' to cancel."
            )
        else:
            reply += f" {reasoning}"
            reply += f" Confirm order for Rs.{amount_paise / 100:.2f}?"

        return reply

    def _handle_confirmation(self, text: str) -> str:
        pending = self._pending
        normalized = text.strip().lower()
        has_upsell = pending["upsell"] is not None

        if normalized in _NEGATIVE:
            self.state = ChatState.AWAITING_CONTINUE_SHOPPING
            self._pending = None
            # Logged so metrics (e.g. gate rejection breakdown) can tell a
            # buyer's explicit decline apart from an unclear reply or an
            # over-bound Gate rejection — none of those share a signature
            # otherwise. Uses the existing audit_log schema, just a new
            # event_type value, same as every other event already does.
            log_event(
                transaction_id=pending["transaction_id"],
                source=SOURCE,
                event_type="order_declined",
                details={"amount_paise": pending["amount_paise"]},
            )
            return "No problem — order cancelled. Would you like to look at anything else?"

        if has_upsell and _matches_primary_only(text, pending["primary"]["name"], pending["upsell"]["name"]):
            return self._confirm(pending, primary_only=True)

        if normalized in _AFFIRMATIVE:
            return self._confirm(pending, primary_only=False)

        # Unclear reply: stay in AWAITING_CONFIRMATION and ask again.
        # Never default to approval (or to any specific path) on an
        # ambiguous response. Logged for the same reason as the decline
        # path above — distinguishable from "declined" and "over-bound".
        log_event(
            transaction_id=pending["transaction_id"],
            source=SOURCE,
            event_type="confirmation_unclear",
            details={"buyer_input": text, "amount_paise": pending["amount_paise"]},
        )
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
        self.state = ChatState.AWAITING_CONTINUE_SHOPPING
        self._pending = None

        if not gate_result["approved"]:
            return f"I can't place that order: {gate_result['reason']} Would you like to look at anything else?"

        order_result = create_order(gate_result, transaction_id=pending["transaction_id"], source=SOURCE)

        if not order_result["success"]:
            return (
                f"Something went wrong placing the order: {order_result['error']} "
                "Would you like to look at anything else?"
            )

        order_id = order_result["order"]["id"]
        if primary_only:
            return (
                f"Order placed. Order ID {order_id}. (Primary item only — the upsell was not included.) "
                "Would you like to look at anything else?"
            )
        return f"Order placed. Order ID {order_id}. Would you like to look at anything else?"

    def _handle_continue_shopping(self, text: str) -> str:
        normalized = text.strip().lower()

        if normalized in _CONTINUE_SHOPPING_NEGATIVE_PHRASES:
            self.state = ChatState.DONE
            self._pending = None
            return "No problem — thanks for shopping with Northlight Outdoors!"

        if normalized in _AFFIRMATIVE:
            self.state = ChatState.AWAITING_REQUEST
            self._pending = None
            return "Great — what would you like to look at?"

        if normalized and normalized not in _CONTINUE_SHOPPING_UNCLEAR_PHRASES:
            # Not a bare yes/no and not a recognized non-answer — treat as
            # an implicit yes carrying its own new product request, and
            # start a completely fresh recommend() cycle for it. This is a
            # brand new, independent transaction: recommend() (called from
            # _handle_request) generates its own fresh transaction_id, so
            # this is never bundled with the previous item's order or Gate
            # check.
            self.state = ChatState.AWAITING_REQUEST
            self._pending = None
            return self._handle_request(_strip_leading_affirmative(text))

        # Ambiguous or empty reply: stay in AWAITING_CONTINUE_SHOPPING and
        # ask again. Same discipline as every other confirmation state in
        # this system — never guess, never silently assume yes or no.
        log_event(
            transaction_id=self.last_transaction_id,
            source=SOURCE,
            event_type="continue_shopping_unclear",
            details={"buyer_input": text},
        )
        return (
            "Sorry, I didn't catch that — would you like to look at anything else? "
            "(yes/no, or tell me what you're looking for)"
        )
