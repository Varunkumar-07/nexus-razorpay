"""Phase 3 smoke test — run sample orders through the Gate and print results.

Run with: python3 scripts/test_gate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gate.gate import AUTO_APPROVAL_LIMIT_PAISE, check_gate


def print_result(label: str, args: dict, result: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"Input: {args}")
    print(f"Result: {result}")


def main() -> None:
    print(f"AUTO_APPROVAL_LIMIT_PAISE = {AUTO_APPROVAL_LIMIT_PAISE} (Rs.{AUTO_APPROVAL_LIMIT_PAISE / 100:,.2f})")

    # Case 1 — valid request within bound, confirmed, with reasoning -> should pass.
    args_1 = {
        "amount_paise": 329_800,  # Arctic Pro (2799) + CloudRest Pad (499) = Rs.3298
        "confirmed": True,
        "reasoning": "Buyer wants a winter sleeping bag under Rs.3000; Arctic Pro fits budget and rating, CloudRest Pad is a compatible upsell.",
    }
    result_1 = check_gate(**args_1)
    print_result("Case 1 — Valid, within bound, confirmed, reasoned (expect PASS)", args_1, result_1)
    assert result_1["approved"] is True, "Case 1 should have passed"

    # Case 2 — Scenario C from the brief: Rs.12,000, over the bound -> should fail.
    args_2 = {
        "amount_paise": 1_200_000,  # Rs.12,000
        "confirmed": True,
        "reasoning": "Buyer wants the AlpineGuard Winter Tent bundle.",
    }
    result_2 = check_gate(**args_2)
    print_result("Case 2 — Scenario C, Rs.12,000 over bound (expect FAIL)", args_2, result_2)
    assert result_2["approved"] is False, "Case 2 should have failed"
    assert "exceeds" in result_2["reason"], "Case 2 reason should mention exceeding the limit"

    # Case 3 — within bound but missing confirmation -> should fail.
    args_3 = {
        "amount_paise": 279_900,  # Arctic Pro alone, Rs.2799 — well within bound
        "confirmed": False,
        "reasoning": "Buyer wants a winter sleeping bag under Rs.3000; Arctic Pro fits budget and rating.",
    }
    result_3 = check_gate(**args_3)
    print_result("Case 3 — Within bound, no confirmation (expect FAIL)", args_3, result_3)
    assert result_3["approved"] is False, "Case 3 should have failed"
    assert "confirm" in result_3["reason"].lower(), "Case 3 reason should mention confirmation"

    print("\nAll gate test cases behaved as expected.")


if __name__ == "__main__":
    main()
