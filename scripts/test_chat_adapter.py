"""Phase 6 smoke test.

Case 1 — full two-turn Scenario A conversation (request -> recommendation ->
"yes" -> order created), audit trail printed and checked.

Case 2 — buyer says "no" at confirmation: no gate check, no order created.

Case 3 — buyer gives an unclear reply at confirmation: session stays
awaiting confirmation (no crash, no default approval), then recovers when
the buyer actually confirms.

Run with: python3 scripts/test_chat_adapter.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audit.audit_log import get_transaction_trail
from app.catalog.seed_data import seed
from app.chat_adapter.adapter import ChatSession, ChatState


def print_trail(transaction_id: str) -> None:
    print(f"\n=== Full audit trail for transaction {transaction_id} ===")
    trail = get_transaction_trail(transaction_id)
    for event in trail:
        print(
            f"\n[{event['id']}] {event['timestamp']} | source={event['source']} "
            f"| event_type={event['event_type']}"
        )
        print(f"    details: {event['details']}")


def case_1_full_scenario_a() -> None:
    print("\n########## CASE 1 — Scenario A, confirmed flow (with the new quantity ask) ##########")
    session = ChatSession()

    turn1 = session.handle_message(
        "I need a good sleeping bag for winter camping, budget around Rs.3000."
    )
    print(f"NEXUS (turn 1): {turn1}")
    # No quantity was stated, so NEXUS must ask before showing any price —
    # see the new AWAITING_QUANTITY state.
    assert session.state == ChatState.AWAITING_QUANTITY, "Should ask for quantity after turn 1 (none was stated)"

    turn1b = session.handle_message("1")
    print(f"NEXUS (turn 1b, quantity answered): {turn1b}")
    assert session.state == ChatState.AWAITING_CONFIRMATION, "Should await confirmation once quantity is known"
    # Scenario A always includes the CloudRest Sleeping Pad upsell, so the
    # three-way prompt (yes / primary only / no) applies — see
    # FAILURE_LOG.md Entry 6.
    assert "Confirm both items" in turn1b, "Confirmation prompt should explicitly ask for confirmation"
    assert "primary only" in turn1b, "Three-way prompt should offer the primary-only path"

    transaction_id = session._pending["transaction_id"]

    turn2 = session.handle_message("yes")
    print(f"NEXUS (turn 2): {turn2}")
    # The order attempt is terminal, but the session now offers a
    # continue-shopping follow-up instead of ending outright.
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "Order placed" in turn2, "Turn 2 should confirm order placement"

    turn3 = session.handle_message("no")
    print(f"NEXUS (turn 3, done shopping): {turn3}")
    assert session.state == ChatState.DONE

    print_trail(transaction_id)

    trail = get_transaction_trail(transaction_id)
    event_types = [e["event_type"] for e in trail]
    assert event_types.count("order_created") == 1, "Exactly one order_created event expected"
    assert all(e["source"] == "chat" for e in trail), "Every event must be tagged source=chat"
    print("\nConfirmed: order created, all events tagged source=chat.")


def case_2_buyer_says_no() -> None:
    print("\n\n########## CASE 2 — buyer says 'no' at confirmation ##########")
    session = ChatSession()

    turn1 = session.handle_message(
        "I need a good sleeping bag for winter camping, budget around Rs.3000."
    )
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_QUANTITY

    turn1b = session.handle_message("1")
    print(f"NEXUS (turn 1b, quantity answered): {turn1b}")
    transaction_id = session._pending["transaction_id"]

    turn2 = session.handle_message("no")
    print(f"NEXUS (turn 2): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "cancel" in turn2.lower()

    turn3 = session.handle_message("no")
    print(f"NEXUS (turn 3, done shopping): {turn3}")
    assert session.state == ChatState.DONE

    trail = get_transaction_trail(transaction_id)
    event_types = [e["event_type"] for e in trail]
    assert "order_created" not in event_types, "No order should be created when buyer says no"
    assert "gate_check" not in event_types, "Gate should not even be checked when buyer declines"
    print("Confirmed: no gate_check, no order_created — order correctly not created.")


def case_3_buyer_says_something_unclear() -> None:
    print("\n\n########## CASE 3 — buyer gives an unclear reply at confirmation ##########")
    session = ChatSession()

    turn1 = session.handle_message(
        "I need a good sleeping bag for winter camping, budget around Rs.3000."
    )
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_QUANTITY

    turn1b = session.handle_message("1")
    print(f"NEXUS (turn 1b, quantity answered): {turn1b}")
    transaction_id = session._pending["transaction_id"]

    turn2 = session.handle_message("maybe later idk")
    print(f"NEXUS (turn 2, unclear): {turn2}")
    assert session.state == ChatState.AWAITING_CONFIRMATION, "Should stay awaiting confirmation"

    trail = get_transaction_trail(transaction_id)
    event_types = [e["event_type"] for e in trail]
    assert "order_created" not in event_types, "No order should be created on an unclear reply"
    print("Confirmed: unclear reply did not crash or default to approval; still awaiting yes/no.")

    turn3 = session.handle_message("yes")
    print(f"NEXUS (turn 3, now confirms): {turn3}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "Order placed" in turn3
    print("Confirmed: session recovers correctly once the buyer actually confirms.")

    turn4 = session.handle_message("no")
    print(f"NEXUS (turn 4, done shopping): {turn4}")
    assert session.state == ChatState.DONE


def main() -> None:
    seed()
    case_1_full_scenario_a()
    case_2_buyer_says_no()
    case_3_buyer_says_something_unclear()
    print("\n\nAll Phase 6 test cases behaved as expected.")


if __name__ == "__main__":
    main()
