"""Phase 8 — Failure Injection.

Two deliberate failure modes, proven graceful on both adapters:

Failure mode 1 — Amount-bound rejection (Scenario C from the brief).
  Already proven via the Agent API Adapter in Phase 7, Case 2: ScoutBot
  requested a tent "under Rs.9000" (its own stated budget), the engine
  recommended the AlpineGuard Winter Tent at Rs.8,999, and the Gate
  rejected it before any Razorpay call was made, because Rs.8,999 exceeds
  the fixed Rs.5,000 auto-approval bound — with a clear reason, fully
  logged (see FAILURE_LOG.md, "Deliberate Failure Scenarios" section).
  Case A below proves the exact same rejection on the CHAT adapter, with
  the same Gate, the same reason format, and no order created — showing
  this is one shared failure path, not two separate implementations that
  happen to look similar.

Failure mode 2 — Razorpay API failure (Case B below).
  A real Razorpay auth error is forced by temporarily invalidating the
  in-process RAZORPAY_KEY_SECRET (the .env file itself is never touched),
  confirming the error is caught, an order_failed event is logged with the
  real error detail, and a clear failure result is returned rather than an
  unhandled crash. Credentials are restored immediately after, and a real
  follow-up order proves the test-mode account is left in working order.

Run with: python3 scripts/test_failure_injection.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audit.audit_log import get_transaction_trail, new_transaction_id
from app.catalog.seed_data import seed
from app.chat_adapter.adapter import ChatSession, ChatState
from app.gate.gate import check_gate
from app.razorpay_integration.orders import create_order


def print_trail(transaction_id: str) -> list:
    print(f"\n=== Full audit trail for transaction {transaction_id} ===")
    trail = get_transaction_trail(transaction_id)
    for event in trail:
        print(
            f"\n[{event['id']}] {event['timestamp']} | source={event['source']} "
            f"| event_type={event['event_type']}"
        )
        print(f"    details: {event['details']}")
    return trail


def case_a_chat_over_bound_rejection() -> None:
    print("\n########## CASE A — Chat Adapter, over-Rs.5000 bundle (should REFUSE) ##########")
    session = ChatSession()

    request = (
        "I'd like to order the Glacier Extreme Sleeping Bag, and please add "
        "the CloudRest Sleeping Pad as well."
    )
    turn1 = session.handle_message(request)
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_CONFIRMATION, "Should be awaiting confirmation after turn 1"

    transaction_id = session._pending["transaction_id"]
    amount_paise = session._pending["amount_paise"]
    print(f"(pending amount: Rs.{amount_paise / 100:.2f})")
    assert amount_paise > 500_000, (
        f"Test premise requires an over-Rs.5000 total to exercise the bound; got Rs.{amount_paise / 100:.2f}. "
        "The LLM picked cheaper products than expected — see FAILURE_LOG.md if this needs investigating."
    )

    turn2 = session.handle_message("yes")
    print(f"NEXUS (turn 2): {turn2}")
    assert session.state == ChatState.DONE
    assert "exceeds" in turn2 and "auto-approval limit" in turn2, (
        "Rejection message should use the same Gate reason format as the agent path"
    )
    assert "Order placed" not in turn2, "No order should be created for an over-bound request"

    trail = print_trail(transaction_id)
    event_types = [e["event_type"] for e in trail]
    assert "order_created" not in event_types, "No order_created event should exist"
    gate_events = [e for e in trail if e["event_type"] == "gate_check"]
    assert len(gate_events) == 1 and gate_events[0]["details"]["approved"] is False
    assert all(e["source"] == "chat" for e in trail), "Every event must be tagged source=chat"
    print(
        "\nConfirmed: Chat Adapter rejection matches the Agent API's rejection from Phase 7 Case 2 — "
        "same Gate, same reason format, no order created, source=chat throughout."
    )


def case_b_razorpay_failure_injection() -> None:
    print("\n\n########## CASE B — simulated Razorpay API failure (invalid credentials) ##########")

    original_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    assert original_secret, "RAZORPAY_KEY_SECRET must already be set (from .env) before this test can run"

    transaction_id = new_transaction_id()
    gate_result = check_gate(
        amount_paise=9_900,  # Rs.99 — trivially within bound, isolates this test to the Razorpay call itself
        confirmed=True,
        reasoning="Failure-injection test: forcing a Razorpay auth error to prove graceful handling.",
        transaction_id=transaction_id,
        source="agent",
    )
    assert gate_result["approved"] is True

    try:
        os.environ["RAZORPAY_KEY_SECRET"] = "invalid_secret_for_failure_injection_test"
        print("Injected an invalid RAZORPAY_KEY_SECRET (in-process only — .env file on disk is untouched)...")
        order_result = create_order(gate_result, transaction_id=transaction_id, source="agent")
    finally:
        os.environ["RAZORPAY_KEY_SECRET"] = original_secret
        print("Restored the real RAZORPAY_KEY_SECRET in this process.")

    print(f"Order result: {order_result}")
    assert order_result["success"] is False, "Order creation should have failed with invalid credentials"
    assert "error" in order_result and order_result["error"], "A real error detail should be present"

    trail = print_trail(transaction_id)
    order_failed_events = [e for e in trail if e["event_type"] == "order_failed"]
    assert len(order_failed_events) == 1, "Exactly one order_failed event expected"
    assert order_failed_events[0]["source"] == "agent"
    print("\nConfirmed: order_failed event logged with the real Razorpay error detail, no unhandled crash.")

    print("\nVerifying credentials are restored to working order with a real follow-up order...")
    verify_transaction_id = new_transaction_id()
    verify_gate_result = check_gate(
        amount_paise=9_900,
        confirmed=True,
        reasoning="Post-failure-injection sanity check: confirming credentials still work.",
        transaction_id=verify_transaction_id,
        source="agent",
    )
    verify_order_result = create_order(verify_gate_result, transaction_id=verify_transaction_id, source="agent")
    print(f"Verification order result: {verify_order_result}")
    assert verify_order_result["success"] is True, "Credentials should be fully restored and working"
    print(
        f"Confirmed: credentials restored — real test-mode order "
        f"{verify_order_result['order']['id']} created successfully after restoration."
    )


def main() -> None:
    seed()
    case_a_chat_over_bound_rejection()
    case_b_razorpay_failure_injection()
    print("\n\nAll Phase 8 failure-injection cases behaved as expected.")


if __name__ == "__main__":
    main()
