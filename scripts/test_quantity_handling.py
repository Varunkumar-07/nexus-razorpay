"""Quantity-handling regression suite.

Covers a real correctness bug found during manual testing: explicit
quantity in a buyer's request (e.g. "AlpineGuard Winter Tent x 2") was
silently dropped — recommend() had no structured field to carry a
quantity at all, so the model fell back to its default one-item +
upsell shape, and the calling code always computed amount as
primary.price + upsell.price (implicitly quantity=1 each). See
FAILURE_LOG.md Entry 5 for full root-cause detail.

Case 1 — explicit quantity, over the Rs.5,000 gate bound: "AlpineGuard
  Winter Tent x 2" -> correct product (AlpineGuard, id=8), quantity=2,
  correct total (unit price x quantity, + optional single-unit upsell),
  and the Gate correctly rejects the TRUE total.

Case 2 — explicit quantity, under the gate bound: "2 CloudRest Sleeping
  Pads" -> correct product (CloudRest, id=15), quantity=2, correct total,
  Gate approves, real order created.

Case 3 — regression: a normal single-item + upsell request with no
  quantity mentioned (Scenario A) still returns quantity=1 and behaves
  exactly as before the fix.

Run with: python3 scripts/test_quantity_handling.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.catalog.seed_data import seed
from app.chat_adapter.adapter import ChatSession, ChatState
from app.reasoning.agent import recommend


def case_1_explicit_quantity_over_bound() -> None:
    print("\n########## CASE 1 — 'AlpineGuard Winter Tent x 2' (explicit quantity, over Rs.5000 bound) ##########")

    # Raw recommend() level — this is where the bug actually lived.
    result = recommend("Tell me about the AlpineGuard Winter Tent x 2", source="debug")
    print(f"recommend(): primary={result['primary']['name']!r}, quantity={result['quantity']}, "
          f"upsell={result['upsell']['name'] if result['upsell'] else None}")
    assert result["no_match"] is False
    assert result["primary"]["id"] == 8, "Primary should be the AlpineGuard Winter Tent (id=8)"
    assert result["quantity"] == 2, f"Expected quantity=2, got {result['quantity']}"

    # Full ChatSession flow — proves the fix reaches the actual amount the
    # Gate evaluates, not just the raw recommend() output.
    session = ChatSession()
    turn1 = session.handle_message("Tell me about the AlpineGuard Winter Tent x 2")
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_CONFIRMATION

    pending_amount = session._pending["amount_paise"]
    floor_amount = 899_900 * 2  # 2x AlpineGuard alone, no upsell
    print(f"Pending amount: {pending_amount} paise (Rs.{pending_amount / 100:.2f})")
    assert pending_amount >= floor_amount, (
        f"Amount must reflect at least 2x AlpineGuard (Rs.{floor_amount / 100:.2f}); "
        f"got Rs.{pending_amount / 100:.2f} — quantity is being dropped"
    )
    assert pending_amount > 500_000, "This total must exceed the Rs.5,000 gate bound either way"

    turn2 = session.handle_message("yes")
    print(f"NEXUS (turn 2): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "exceeds" in turn2 and "auto-approval limit" in turn2, "Gate should reject with the standard reason"
    assert "Order placed" not in turn2, "No order should be created for a rejected request"

    turn3 = session.handle_message("no")
    print(f"NEXUS (turn 3, done shopping): {turn3}")
    assert session.state == ChatState.DONE

    print("Confirmed: quantity correctly parsed as 2, correct product, Gate correctly rejects the true total.")


def case_2_explicit_quantity_under_bound() -> None:
    print("\n\n########## CASE 2 — '2 CloudRest Sleeping Pads' (explicit quantity, under Rs.5000 bound) ##########")

    result = recommend(
        "I want exactly 2 CloudRest Sleeping Pads, nothing else.", source="debug"
    )
    print(f"recommend(): primary={result['primary']['name']!r}, quantity={result['quantity']}, "
          f"upsell={result['upsell']['name'] if result['upsell'] else None}")
    assert result["no_match"] is False
    assert result["primary"]["id"] == 15, "Primary should be the CloudRest Sleeping Pad (id=15)"
    assert result["quantity"] == 2, f"Expected quantity=2, got {result['quantity']}"

    session = ChatSession()
    turn1 = session.handle_message("I want exactly 2 CloudRest Sleeping Pads, nothing else.")
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_CONFIRMATION

    pending_amount = session._pending["amount_paise"]
    floor_amount = 49_900 * 2  # 2x CloudRest alone
    print(f"Pending amount: {pending_amount} paise (Rs.{pending_amount / 100:.2f})")
    assert pending_amount >= floor_amount
    assert pending_amount <= 500_000, (
        f"Expected this to stay within the Rs.5,000 bound; got Rs.{pending_amount / 100:.2f}"
    )

    turn2 = session.handle_message("yes")
    print(f"NEXUS (turn 2): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "Order placed" in turn2, "Gate should approve and a real order should be created"

    turn3 = session.handle_message("no")
    print(f"NEXUS (turn 3, done shopping): {turn3}")
    assert session.state == ChatState.DONE

    print("Confirmed: quantity correctly parsed as 2, correct product, Gate correctly approves the true total.")


def case_3_no_quantity_regression() -> None:
    print("\n\n########## CASE 3 — Scenario A, no quantity mentioned (regression check) ##########")

    result = recommend(
        "I need a good sleeping bag for winter camping, budget around Rs.3000.", source="debug"
    )
    print(f"recommend(): primary={result['primary']['name']!r}, quantity={result['quantity']}, "
          f"upsell={result['upsell']['name'] if result['upsell'] else None}")
    assert result["no_match"] is False
    assert result["primary"]["id"] == 1, "Primary should still be the Arctic Pro Sleeping Bag (id=1)"
    assert result["quantity"] == 1, f"No quantity was mentioned — expected quantity=1, got {result['quantity']}"
    assert result["upsell"] is not None and result["upsell"]["id"] == 15, "Upsell should still be CloudRest Sleeping Pad"

    session = ChatSession()
    turn1 = session.handle_message("I need a good sleeping bag for winter camping, budget around Rs.3000.")
    print(f"NEXUS (turn 1): {turn1}")
    # No quantity was stated, so the new AWAITING_QUANTITY ask kicks in first
    # (Part A) — this is itself the regression check that "no quantity
    # mentioned" is handled, distinct from Entry 5's "explicit quantity"
    # cases above.
    assert session.state == ChatState.AWAITING_QUANTITY

    turn1b = session.handle_message("1")
    print(f"NEXUS (turn 1b, quantity answered): {turn1b}")
    assert session.state == ChatState.AWAITING_CONFIRMATION
    assert session._pending["amount_paise"] == 279_900 + 49_900, "Amount should be unchanged from before the fix"

    turn2 = session.handle_message("yes")
    print(f"NEXUS (turn 2): {turn2}")
    assert "Order placed" in turn2

    print("Confirmed: Scenario A (no quantity) is completely unaffected by the Entry 5 fix.")


def main() -> None:
    seed()
    case_1_explicit_quantity_over_bound()
    case_2_explicit_quantity_under_bound()
    case_3_no_quantity_regression()
    print("\n\nAll quantity-handling test cases behaved as expected.")


if __name__ == "__main__":
    main()
