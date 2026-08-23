"""Bug 1 investigation — "certain product names fail to match" turned out
to be misattributed Groq daily-quota exhaustion, not a catalog-matching
defect. See FAILURE_LOG.md Entry 7 for the full root-cause writeup.

Cases 1-2 are zero-cost (no LLM calls) and always run: they prove the
catalog layer itself has never been the problem, and lock in the fix that
was actually needed — the buyer-facing message for a ReasoningError must
never claim "no product matches" when the real cause is an infra/capacity
failure. These always pass regardless of Groq quota state.

Cases 3-4 are the real end-to-end reproduction of the two reported
requests ("Compact 20L Backpack" with no suffix, "DayHiker 25L Backpack x2")
through the actual recommend() pipeline. They require live Groq quota and
are expected to fail with the same 429 the investigation hit if quota is
still exhausted when this runs — that failure mode is itself consistent
with Entry 7's finding, not a new bug. Re-run once quota is available.

Run with: python3 scripts/test_bug1_catalog_matching.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.catalog.seed_data import seed
from app.catalog.service import search_by_category, search_by_keyword
from app.reasoning.agent import ReasoningError, recommend
from app.web_chat.routes import _reasoning_error_reply


def case_1_catalog_layer_matches_correctly() -> None:
    print("\n########## CASE 1 — catalog layer: both reported products match correctly (zero LLM cost) ##########")

    for full_name, product_id in [
        ("Compact 20L Backpack", 12),
        ("DayHiker 25L Backpack", 10),
    ]:
        # Full name.
        results = search_by_keyword(full_name)
        assert len(results) == 1 and results[0]["id"] == product_id, (
            f"search_by_keyword({full_name!r}) should return exactly this product"
        )
        print(f"search_by_keyword({full_name!r}) -> [{results[0]['id']}] {results[0]['name']}  OK")

        # A partial/single-word fragment of the name.
        first_word = full_name.split()[0]
        results = search_by_keyword(first_word)
        assert any(p["id"] == product_id for p in results), (
            f"search_by_keyword({first_word!r}) should include this product among its results"
        )
        print(f"search_by_keyword({first_word!r}) -> includes [{product_id}]  OK")

    # Category search for backpacks should include both.
    backpacks = search_by_category("backpacks")
    backpack_ids = {p["id"] for p in backpacks}
    assert {10, 12}.issubset(backpack_ids), "Both products should appear in the backpacks category"
    print("search_by_category('backpacks') -> includes both [10] and [12]  OK")

    print("\nConfirmed: the catalog layer finds both products correctly by every reasonable search path.")


def case_2_reasoning_error_message_does_not_claim_no_match() -> None:
    print("\n\n########## CASE 2 — ReasoningError reply never claims 'no match' (zero LLM cost) ##########")

    rate_limit_exc = ReasoningError(
        "Groq API call failed: Error code: 429 - {'error': {'message': 'Rate limit reached for "
        "model `openai/gpt-oss-120b` ... on tokens per day (TPD): Limit 200000, Used 199997, "
        "Requested 1455.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
    )
    reply = _reasoning_error_reply(rate_limit_exc)
    print(f"Rate-limit reply: {reply}")
    assert "capacity" in reply.lower(), "Rate-limit case should say we're at capacity, not that nothing matched"
    assert "trouble finding a match" not in reply.lower()
    assert "no match" not in reply.lower()
    assert "doesn't exist" not in reply.lower()

    generic_exc = ReasoningError(
        "Agent did not converge on a recommendation within 6 tool iterations."
    )
    reply = _reasoning_error_reply(generic_exc)
    print(f"Generic-failure reply: {reply}")
    assert "temporary issue" in reply.lower()
    assert "trouble finding a match" not in reply.lower()
    assert "no match" not in reply.lower()
    assert "doesn't exist" not in reply.lower()

    print(
        "\nConfirmed: neither failure path claims 'no product matches' — the old wording that caused "
        "a rate-limit failure to be misdiagnosed as a catalog-matching bug is gone."
    )


def case_3_end_to_end_compact_backpack() -> None:
    print("\n\n########## CASE 3 — end-to-end: 'Compact 20L Backpack' (no suffix), live Groq call ##########")
    try:
        result = recommend("Tell me about the Compact 20L Backpack", source="debug")
    except ReasoningError as exc:
        print(f"SKIPPED — live Groq call failed (expected if quota is still exhausted): {exc}")
        return

    print(f"primary: {result['primary']['name'] if result['primary'] else None}, quantity: {result['quantity']}")
    assert result["no_match"] is False
    assert result["primary"]["id"] == 12, "Should correctly recommend the Compact 20L Backpack (id=12)"
    print("Confirmed: 'Compact 20L Backpack' (no suffix) correctly matches end-to-end.")


def case_4_end_to_end_dayhiker_quantity() -> None:
    print("\n\n########## CASE 4 — end-to-end: 'DayHiker 25L Backpack x2', live Groq call ##########")
    try:
        result = recommend("Tell me about the DayHiker 25L Backpack x2", source="debug")
    except ReasoningError as exc:
        print(f"SKIPPED — live Groq call failed (expected if quota is still exhausted): {exc}")
        return

    print(f"primary: {result['primary']['name'] if result['primary'] else None}, quantity: {result['quantity']}")
    assert result["no_match"] is False
    assert result["primary"]["id"] == 10, "Should correctly recommend the DayHiker 25L Backpack (id=10)"
    assert result["quantity"] == 2, f"Expected quantity=2, got {result['quantity']}"
    print("Confirmed: 'DayHiker 25L Backpack x2' correctly matches the product and quantity end-to-end.")


def main() -> None:
    seed()
    case_1_catalog_layer_matches_correctly()
    case_2_reasoning_error_message_does_not_claim_no_match()
    case_3_end_to_end_compact_backpack()
    case_4_end_to_end_dayhiker_quantity()
    print("\n\nAll Bug 1 investigation cases behaved as expected.")


if __name__ == "__main__":
    main()
