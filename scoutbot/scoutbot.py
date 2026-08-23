"""ScoutBot — a second, self-built AI buyer agent (Phase 7, Part B).

ScoutBot is a genuinely separate agent from NEXUS: it receives a plain
instruction, does its own simple instruction parsing and product selection,
then talks to the NEXUS Agent API Adapter over real HTTP (never importing
NEXUS's Python modules directly) to get an official recommendation and
place an order.

Run standalone (NEXUS Agent API must already be running):
    python3 scoutbot/scoutbot.py "Buy one tent under Rs.5000 from Northlight Outdoors"
"""

import re
import sys
from typing import Optional

import requests

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"

# Longest/most specific phrases first, so "sleeping bag" matches before a
# looser single-word rule could.
_CATEGORY_SYNONYMS = [
    ("sleeping bags", "sleeping_bags"),
    ("sleeping bag", "sleeping_bags"),
    ("sleeping pad", "accessories"),
    ("sleeping mat", "accessories"),
    ("cooking gear", "cooking_gear"),
    ("cook set", "cooking_gear"),
    ("backpacks", "backpacks"),
    ("backpack", "backpacks"),
    ("tents", "tents"),
    ("tent", "tents"),
    ("stove", "cooking_gear"),
    ("accessories", "accessories"),
    ("accessory", "accessories"),
]

_PRICE_PATTERN = re.compile(r"rs\.?\s*([\d,]+)", re.IGNORECASE)


def parse_instruction(instruction: str) -> dict:
    """Extract a category and a max budget (in paise) from a plain instruction.

    Deliberately simple pattern matching — this is ScoutBot's "own logic",
    not an LLM call.
    """
    lowered = instruction.lower()

    category = None
    for phrase, mapped in _CATEGORY_SYNONYMS:
        if phrase in lowered:
            category = mapped
            break

    max_price_paise = None
    match = _PRICE_PATTERN.search(lowered)
    if match:
        rupees = int(match.group(1).replace(",", ""))
        max_price_paise = rupees * 100

    return {"category": category, "max_price_paise": max_price_paise}


def pick_best_fit(candidates: list, max_price_paise: Optional[int]) -> Optional[dict]:
    """ScoutBot's own product-selection logic: best fit under budget.

    If a budget is given, pick the highest-priced candidate at or under it
    (uses the budget most fully). Otherwise, pick the cheapest candidate.
    """
    if not candidates:
        return None
    if max_price_paise is not None:
        affordable = [p for p in candidates if p["price_paise"] <= max_price_paise]
        if not affordable:
            return None
        return max(affordable, key=lambda p: p["price_paise"])
    return min(candidates, key=lambda p: p["price_paise"])


def buy(instruction: str, api_base_url: str = DEFAULT_API_BASE_URL) -> dict:
    """Run ScoutBot's full buying process against a live NEXUS Agent API.

    Prints its decision process live, then returns a summary dict.
    """
    print(f"ScoutBot: received instruction: {instruction!r}")

    intent = parse_instruction(instruction)
    print(
        f"ScoutBot: parsed intent -> category={intent['category']!r}, "
        f"max_price_paise={intent['max_price_paise']!r}"
    )

    search_resp = requests.get(
        f"{api_base_url}/catalog/search",
        params={k: v for k, v in intent.items() if v is not None},
        timeout=15,
    )
    search_resp.raise_for_status()
    candidates = search_resp.json()
    print(f"ScoutBot: catalog search returned {len(candidates)} candidate(s):")
    for c in candidates:
        print(f"    - [{c['id']}] {c['name']} — Rs.{c['price_paise'] / 100:.2f}")

    choice = pick_best_fit(candidates, intent["max_price_paise"])
    if choice is None:
        print("ScoutBot: no candidate fits the budget — giving up.")
        return {"success": False, "reason": "no_candidate_fits_budget", "transaction_id": None}

    print(
        f"ScoutBot: my own pick -> [{choice['id']}] {choice['name']} "
        f"(Rs.{choice['price_paise'] / 100:.2f}) — best fit under budget."
    )

    recommend_resp = requests.post(
        f"{api_base_url}/recommend",
        json={
            "category": intent["category"],
            "max_price_paise": intent["max_price_paise"],
            "keywords": None,
        },
        timeout=15,
    )
    recommend_resp.raise_for_status()
    recommendation = recommend_resp.json()
    print(f"ScoutBot: NEXUS /recommend responded, transaction_id={recommendation['transaction_id']}")

    if recommendation["no_match"] or not recommendation["primary"]:
        print("ScoutBot: NEXUS engine reports no_match — aborting.")
        return {
            "success": False,
            "reason": "engine_no_match",
            "transaction_id": recommendation["transaction_id"],
            "recommendation": recommendation,
        }

    primary = recommendation["primary"]
    if primary["id"] != choice["id"]:
        print(
            f"ScoutBot: note — NEXUS's pick ([{primary['id']}] {primary['name']}) differs from "
            "my own pick; proceeding with NEXUS's official recommendation."
        )

    amount_paise = primary["price_paise"]
    reasoning = (
        f"ScoutBot selected {primary['name']} as the best fit under a "
        f"Rs.{(intent['max_price_paise'] or 0) / 100:.2f} budget, for the instruction: "
        f"{instruction!r}."
    )
    print(f"ScoutBot: my reasoning -> {reasoning}")
    print(f"ScoutBot: placing order for Rs.{amount_paise / 100:.2f}...")

    order_resp = requests.post(
        f"{api_base_url}/order",
        json={
            "transaction_id": recommendation["transaction_id"],
            "amount_paise": amount_paise,
            "confirmed": True,
            "reasoning": reasoning,
        },
        timeout=15,
    )
    order_resp.raise_for_status()
    order_result = order_resp.json()

    if order_result["approved"] and order_result.get("order"):
        print(f"ScoutBot: order placed. Order ID {order_result['order']['id']}.")
    elif order_result["approved"]:
        print(f"ScoutBot: gate approved but order creation failed: {order_result['reason']}")
    else:
        print(f"ScoutBot: order REFUSED by the Gate: {order_result['reason']}")

    return {
        "success": bool(order_result["approved"] and order_result.get("order")),
        "transaction_id": recommendation["transaction_id"],
        "recommendation": recommendation,
        "order_result": order_result,
    }


if __name__ == "__main__":
    instruction_arg = " ".join(sys.argv[1:]) or "Buy one tent under Rs.5000 from Northlight Outdoors."
    buy(instruction_arg)
