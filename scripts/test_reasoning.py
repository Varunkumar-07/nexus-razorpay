"""Phase 2 smoke test — run buyer requests through the Agent Reasoning Core
and print the structured recommendation.

Run with: python3 scripts/test_reasoning.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.catalog.seed_data import seed
from app.reasoning.agent import ReasoningError, recommend


def print_recommendation(label: str, request: str, result: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"Request: {request!r}")
    print(f"no_match: {result['no_match']}")

    primary = result["primary"]
    if primary:
        print(
            f"Primary: [{primary['id']}] {primary['name']} — "
            f"Rs.{primary['price_paise'] / 100:.2f} — {primary['spec']}"
        )
    else:
        print("Primary: (none)")

    upsell = result["upsell"]
    if upsell:
        print(
            f"Upsell:  [{upsell['id']}] {upsell['name']} — "
            f"Rs.{upsell['price_paise'] / 100:.2f} — {upsell['spec']}"
        )
    else:
        print("Upsell:  (none)")

    print(f"Reasoning: {result['reasoning']}")


def main() -> None:
    seed()

    # Scenario A from the project brief — should surface Arctic Pro Sleeping
    # Bag as primary and CloudRest Sleeping Pad as the upsell.
    scenario_a_request = "I need a good sleeping bag for winter camping, budget around Rs.3000."
    try:
        result_a = recommend(scenario_a_request)
        print_recommendation("Scenario A — Winter Sleeping Bag", scenario_a_request, result_a)
    except ReasoningError as exc:
        print(f"\n=== Scenario A — FAILED ===\n{exc}")
        raise

    # No clean match — budget too low for anything in the catalog.
    no_match_request = "I need a 4-season winter tent, budget around Rs.200."
    try:
        result_b = recommend(no_match_request)
        print_recommendation("No-Match Case — Unrealistic Budget", no_match_request, result_b)
    except ReasoningError as exc:
        print(f"\n=== No-Match Case — FAILED ===\n{exc}")
        raise


if __name__ == "__main__":
    main()
