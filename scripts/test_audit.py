"""Phase 4 smoke test — run one full flow (recommendation -> gate check)
and print the resulting audit trail in chronological order.

Run with: python3 scripts/test_audit.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audit.audit_log import get_transaction_trail
from app.catalog.seed_data import seed
from app.gate.gate import check_gate
from app.reasoning.agent import recommend


def main() -> None:
    seed()

    request = "I need a good sleeping bag for winter camping, budget around Rs.3000."
    result = recommend(request, source="chat")
    transaction_id = result["transaction_id"]

    print(f"Transaction: {transaction_id}")
    print(f"Primary: {result['primary']['name'] if result['primary'] else None}")
    print(f"Upsell: {result['upsell']['name'] if result['upsell'] else None}")

    amount_paise = 0
    if result["primary"]:
        amount_paise += result["primary"]["price_paise"]
    if result["upsell"]:
        amount_paise += result["upsell"]["price_paise"]

    gate_result = check_gate(
        amount_paise=amount_paise,
        confirmed=True,
        reasoning=result["reasoning"],
        transaction_id=transaction_id,
        source="chat",
    )
    print(f"Gate result: {gate_result}")

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


if __name__ == "__main__":
    main()
