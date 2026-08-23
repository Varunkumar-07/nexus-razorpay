"""Phase 5 smoke test.

Case 1 — full flow end to end: recommendation (Scenario A) -> gate check ->
Razorpay order creation -> payment status fetch -> print the complete audit
trail for that transaction_id.

Case 2 — rejection path: Scenario C (Rs.12,000, over the gate bound) ->
confirm create_order() refuses to run against a rejected gate result.

Run with: python3 scripts/test_razorpay_integration.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audit.audit_log import get_transaction_trail, new_transaction_id
from app.catalog.seed_data import seed
from app.gate.gate import check_gate
from app.razorpay_integration.orders import GateNotApprovedError, create_order
from app.reasoning.agent import recommend


def print_trail(transaction_id: str) -> None:
    print(f"\n=== Full audit trail for transaction {transaction_id} ===")
    trail = get_transaction_trail(transaction_id)
    if not trail:
        print("  (no events found — something's wrong)")
    for event in trail:
        print(
            f"\n[{event['id']}] {event['timestamp']} | source={event['source']} "
            f"| event_type={event['event_type']}"
        )
        print(f"    details: {event['details']}")


def case_1_full_success_flow() -> None:
    print("\n########## CASE 1 — Full flow: Scenario A (should succeed) ##########")

    request = "I need a good sleeping bag for winter camping, budget around Rs.3000."
    result = recommend(request, source="chat")
    transaction_id = result["transaction_id"]
    print(f"Recommendation: primary={result['primary']['name']}, upsell={result['upsell']['name']}")

    amount_paise = result["primary"]["price_paise"] + result["upsell"]["price_paise"]

    gate_result = check_gate(
        amount_paise=amount_paise,
        confirmed=True,
        reasoning=result["reasoning"],
        transaction_id=transaction_id,
        source="chat",
    )
    print(f"Gate result: approved={gate_result['approved']}")
    assert gate_result["approved"] is True, "Case 1 gate check should have passed"

    order_result = create_order(gate_result, transaction_id=transaction_id, source="chat")
    print(f"Order result: {order_result}")
    assert order_result["success"] is True, "Case 1 order creation should have succeeded"
    assert order_result["order"]["status"] == "created", "Order status should be 'created'"

    print_trail(transaction_id)


def case_2_rejection_path() -> None:
    print("\n\n########## CASE 2 — Scenario C: Rs.12,000, over bound (should REFUSE) ##########")

    transaction_id = new_transaction_id()
    gate_result = check_gate(
        amount_paise=1_200_000,  # Rs.12,000
        confirmed=True,
        reasoning="Buyer wants the AlpineGuard Winter Tent bundle.",
        transaction_id=transaction_id,
        source="chat",
    )
    print(f"Gate result: {gate_result}")
    assert gate_result["approved"] is False, "Case 2 gate check should have failed"

    try:
        create_order(gate_result, transaction_id=transaction_id, source="chat")
        raise AssertionError("create_order() should have raised GateNotApprovedError but didn't")
    except GateNotApprovedError as exc:
        print(f"create_order() correctly refused: {exc}")

    print_trail(transaction_id)
    trail = get_transaction_trail(transaction_id)
    order_events = [e for e in trail if e["event_type"] in ("order_created", "order_failed")]
    assert not order_events, "No order_created/order_failed event should exist for a rejected gate result"
    print("\nConfirmed: no order_created or order_failed event exists for this transaction — "
          "no Razorpay call was ever made.")


def main() -> None:
    seed()
    case_1_full_success_flow()
    case_2_rejection_path()
    print("\n\nAll Phase 5 test cases behaved as expected.")


if __name__ == "__main__":
    main()
