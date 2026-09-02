"""Upsell-decline regression suite.

Covers a real product gap found during manual testing: once an upsell was
offered alongside a primary recommendation, the confirmation flow only
recognized "yes" (accept both) or "no" (cancel everything) — there was no
way to accept just the primary item and decline the upsell without
cancelling the whole order. See FAILURE_LOG.md Entry 6 for full detail.

Case 1 — accept both (existing behavior, must still work): "yes" on a
  recommendation with an upsell confirms the full bundle amount and
  creates one order for both items.

Case 2 — decline the upsell, accept the primary only, Gate approves: a
  recognized primary-only phrase re-checks the Gate against the smaller,
  correct amount (primary price x quantity, no upsell) and creates an
  order for that amount only.

Case 2b — same, via a natural "I just want the X" phrase (the Camp Cook
  Set example from the bug report), not just the literal "primary only".

Case 2c — decline the upsell, accept the primary only, Gate still
  correctly REJECTS: the ExpeditionMax 65L Backpack (Rs.5,499 alone)
  already exceeds the Rs.5,000 bound even without its upsell. Proves the
  Gate re-check is real — primary-only is never a rubber stamp.

Case 3 — full decline (existing "no" behavior, must still work): declines
  everything, no Gate check at all, no order.

Case 4 — ambiguous input during the three-way confirmation: neither yes,
  primary-only, nor no -> clarifying re-ask, session stays in
  AWAITING_CONFIRMATION, no Gate check, no guessing.

Case 5 — regression: Scenario A, Entry 5 (quantity), and the existing
  Phase 6 two-way (no-upsell) flow are unaffected by this change.

Run with: python3 scripts/test_upsell_decline.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audit.audit_log import get_transaction_trail
from app.catalog.seed_data import seed
from app.chat_adapter.adapter import ChatSession, ChatState

SCENARIO_A_REQUEST = "I need a good sleeping bag for winter camping, budget around Rs.3000."


def _get_session_with_upsell(request: str, max_attempts: int = 5):
    """Send `request` in a fresh session, retrying with fresh sessions until
    the LLM actually offers an upsell (its upsell decision isn't pinned to
    temperature=0, so it varies run to run — the assertions in these cases
    are about the primary-only *mechanism*, not about forcing an upsell to
    appear, so we retry rather than let unrelated variability fail the test).

    `request` here never states a quantity, so turn 1 now lands in the new
    AWAITING_QUANTITY state (Part A) before confirmation — this answers "1"
    on the caller's behalf and returns the resulting confirmation prompt as
    `turn1`, so every existing caller (which only cares about the
    confirmation-stage text/pending state) is unaffected.
    """
    for attempt in range(1, max_attempts + 1):
        session = ChatSession()
        turn1 = session.handle_message(request)
        if session.state == ChatState.AWAITING_QUANTITY:
            turn1 = session.handle_message("1")
        if session._pending is not None and session._pending["upsell"] is not None:
            return session, turn1
        print(f"(attempt {attempt}: no upsell offered this run, retrying with a fresh session)")
    raise AssertionError(f"No upsell was offered for {request!r} after {max_attempts} attempts")


def _decline_continue_shopping(session: ChatSession) -> str:
    """Send the trailing 'no' at AWAITING_CONTINUE_SHOPPING and confirm the
    session reaches true DONE — the terminal state every existing case here
    used to reach directly, now one turn later (Part B).
    """
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    final = session.handle_message("no")
    assert session.state == ChatState.DONE
    return final


def case_1_accept_both() -> None:
    print("\n########## CASE 1 — accept both items ('yes') ##########")
    session, turn1 = _get_session_with_upsell(SCENARIO_A_REQUEST)
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_CONFIRMATION
    pending = session._pending
    full_amount = pending["amount_paise"]
    transaction_id = pending["transaction_id"]

    turn2 = session.handle_message("yes")
    print(f"NEXUS (turn 2): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "Order placed" in turn2
    assert "primary item only" not in turn2.lower(), "Full-bundle order should not say 'primary item only'"
    _decline_continue_shopping(session)

    trail = get_transaction_trail(transaction_id)
    gate_events = [e for e in trail if e["event_type"] == "gate_check"]
    assert len(gate_events) == 1
    assert gate_events[0]["details"]["amount_paise"] == full_amount, "Gate should have evaluated the FULL bundle amount"
    assert gate_events[0]["details"]["approved"] is True
    assert any(e["event_type"] == "order_created" for e in trail)

    print(f"Confirmed: full bundle (Rs.{full_amount / 100:.2f}) accepted, Gate checked the true bundle amount, order created.")


def case_2_decline_upsell_primary_only_approved() -> None:
    print("\n\n########## CASE 2 — decline upsell, primary only, Gate approves ##########")
    session, turn1 = _get_session_with_upsell(SCENARIO_A_REQUEST)
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_CONFIRMATION
    pending = session._pending
    full_amount = pending["amount_paise"]
    primary_only_amount = pending["primary_only_amount_paise"]
    transaction_id = pending["transaction_id"]
    print(f"Full bundle: Rs.{full_amount / 100:.2f} | Primary only: Rs.{primary_only_amount / 100:.2f}")
    assert primary_only_amount < full_amount, "Primary-only amount must be strictly smaller than the bundle"
    assert primary_only_amount == pending["primary"]["price_paise"] * pending["quantity"]

    turn2 = session.handle_message("primary only")
    print(f"NEXUS (turn 2): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "Order placed" in turn2, "Primary-only should still place a real order when it's within the Gate bound"
    assert "primary item only" in turn2.lower()
    _decline_continue_shopping(session)

    trail = get_transaction_trail(transaction_id)
    gate_events = [e for e in trail if e["event_type"] == "gate_check"]
    assert len(gate_events) == 1, "Exactly one gate_check event — the Gate must be re-run, not skipped"
    assert gate_events[0]["details"]["amount_paise"] == primary_only_amount, (
        "Gate must have evaluated the SMALLER primary-only amount, not the full bundle"
    )
    assert gate_events[0]["details"]["approved"] is True

    order_events = [e for e in trail if e["event_type"] == "order_created"]
    assert len(order_events) == 1
    assert order_events[0]["details"]["order"]["amount"] == primary_only_amount, (
        "The real Razorpay order must be for the primary-only amount"
    )

    print(
        f"Confirmed: upsell declined, Gate re-evaluated against Rs.{primary_only_amount / 100:.2f} "
        "(not the bundle), real order created for the primary item only."
    )


def case_2b_decline_upsell_natural_phrase() -> None:
    print("\n\n########## CASE 2b — primary-only via a natural 'just the X' phrase (Camp Cook Set) ##########")
    session = ChatSession()

    turn1 = session.handle_message("Tell me about the Camp Cook Set (4-piece)")
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_QUANTITY
    turn1b = session.handle_message("1")
    print(f"NEXUS (turn 1b, quantity answered): {turn1b}")
    assert session.state == ChatState.AWAITING_CONFIRMATION
    pending = session._pending
    if pending["upsell"] is None:
        print("(No upsell offered for this request this run — nothing to decline; skipping.)")
        return

    primary_only_amount = pending["primary_only_amount_paise"]

    turn2 = session.handle_message("i just want the Camp Cook Set (4-piece)")
    print(f"NEXUS (turn 2): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "Order placed" in turn2
    assert "primary item only" in turn2.lower()
    _decline_continue_shopping(session)
    print(
        f"Confirmed: natural phrasing 'i just want the X' correctly recognized as primary-only "
        f"(Rs.{primary_only_amount / 100:.2f})."
    )


def case_2c_decline_upsell_primary_only_still_rejected() -> None:
    print("\n\n########## CASE 2c — primary-only, but the primary ALONE still exceeds Rs.5000 (Gate still rejects) ##########")
    session, turn1 = _get_session_with_upsell("Tell me about the ExpeditionMax 65L Backpack")
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_CONFIRMATION
    pending = session._pending
    primary_only_amount = pending["primary_only_amount_paise"]
    transaction_id = pending["transaction_id"]
    print(f"Primary alone: Rs.{primary_only_amount / 100:.2f}")
    assert primary_only_amount > 500_000, (
        "Test premise: the ExpeditionMax Backpack alone must already exceed the Rs.5,000 bound"
    )

    turn2 = session.handle_message("primary only")
    print(f"NEXUS (turn 2): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "Order placed" not in turn2, "Gate must still reject — primary-only is not a bypass"
    assert "exceeds" in turn2 and "auto-approval limit" in turn2
    _decline_continue_shopping(session)

    trail = get_transaction_trail(transaction_id)
    gate_events = [e for e in trail if e["event_type"] == "gate_check"]
    assert len(gate_events) == 1
    assert gate_events[0]["details"]["amount_paise"] == primary_only_amount, "Gate evaluated the primary-only amount"
    assert gate_events[0]["details"]["approved"] is False
    assert not any(e["event_type"] == "order_created" for e in trail)

    print(
        "Confirmed: primary-only is genuinely re-gated, not a rubber stamp — the Gate correctly "
        "still rejects when the primary item alone exceeds the Rs.5,000 bound."
    )


def case_3_full_decline() -> None:
    print("\n\n########## CASE 3 — full decline ('no') still works ##########")
    session = ChatSession()

    turn1 = session.handle_message(SCENARIO_A_REQUEST)
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_QUANTITY
    turn1b = session.handle_message("1")
    print(f"NEXUS (turn 1b, quantity answered): {turn1b}")
    transaction_id = session._pending["transaction_id"]

    turn2 = session.handle_message("no")
    print(f"NEXUS (turn 2): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "cancel" in turn2.lower()
    _decline_continue_shopping(session)

    trail = get_transaction_trail(transaction_id)
    event_types = [e["event_type"] for e in trail]
    assert "gate_check" not in event_types, "Gate should not even be checked on full decline"
    assert "order_created" not in event_types

    print("Confirmed: full decline still cancels everything, no Gate check, no order.")


def case_4_ambiguous_input() -> None:
    print("\n\n########## CASE 4 — ambiguous input during the three-way confirmation ##########")
    session, turn1 = _get_session_with_upsell(SCENARIO_A_REQUEST)
    print(f"NEXUS (turn 1): {turn1}")
    transaction_id = session._pending["transaction_id"]

    turn2 = session.handle_message("maybe, not sure")
    print(f"NEXUS (turn 2, ambiguous): {turn2}")
    assert session.state == ChatState.AWAITING_CONFIRMATION, "Ambiguous input must not advance the state"
    assert "primary only" in turn2, "Clarifying re-ask should mention all three options"

    trail = get_transaction_trail(transaction_id)
    event_types = [e["event_type"] for e in trail]
    assert "gate_check" not in event_types, "No guessing — Gate must not be checked on ambiguous input"
    assert "order_created" not in event_types

    # Recovery: the session should still work correctly afterward.
    turn3 = session.handle_message("primary only")
    print(f"NEXUS (turn 3, now clear): {turn3}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "Order placed" in turn3
    _decline_continue_shopping(session)

    print("Confirmed: ambiguous input triggers a clarifying re-ask (no guessing), and the session recovers correctly.")


def case_5_regression_no_upsell_and_quantity() -> None:
    print("\n\n########## CASE 5 — regression: no-upsell flow and quantity handling unaffected ##########")

    # No-upsell path: explicit quantity for a single item with "nothing else" —
    # should behave exactly like the original two-way yes/no flow.
    session = ChatSession()
    turn1 = session.handle_message("I want exactly 2 CloudRest Sleeping Pads, nothing else.")
    print(f"NEXUS (turn 1): {turn1}")
    pending = session._pending
    if pending["upsell"] is not None:
        print("(An upsell was offered this run for the no-upsell test message — skipping this sub-check.)")
    else:
        assert "Confirm order for Rs." in turn1, "No-upsell prompt should be the original two-way wording"
        assert "Confirm both items" not in turn1

    turn2 = session.handle_message("yes")
    print(f"NEXUS (turn 2): {turn2}")
    assert "Order placed" in turn2

    print("Confirmed: no-upsell flow keeps its original two-way wording, quantity handling unaffected.")


def main() -> None:
    seed()
    case_1_accept_both()
    case_2_decline_upsell_primary_only_approved()
    case_2b_decline_upsell_natural_phrase()
    case_2c_decline_upsell_primary_only_still_rejected()
    case_3_full_decline()
    case_4_ambiguous_input()
    case_5_regression_no_upsell_and_quantity()
    print("\n\nAll upsell-decline test cases behaved as expected.")


if __name__ == "__main__":
    main()
