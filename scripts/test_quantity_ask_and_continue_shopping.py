"""Chat Adapter enhancement — quantity ask + continue-shopping loop.

Two new conversation states layered onto the existing ChatSession state
machine (app/chat_adapter/adapter.py): AWAITING_QUANTITY and
AWAITING_CONTINUE_SHOPPING. Neither weakens any existing guarantee — the
Gate is still re-checked on every order, every product still gets its own
reasoning and its own fully-audited transaction, and no path here defaults
to approval or silently guesses at an ambiguous reply.

Part A — AWAITING_QUANTITY
Case 1 — quantity ask triggers when the request doesn't state one, rejects
  an unrecognizable reply without guessing, then proceeds once answered.
Case 2 — quantity ask is skipped entirely when the request already states
  one explicitly (Entry 5's existing behavior, unchanged).

Part B — AWAITING_CONTINUE_SHOPPING
Case 3 — after an order attempt, a clear "yes" starts a brand new
  recommend() cycle: its own transaction_id, its own Gate check, its own
  audit trail — never bundled with the first order.
Case 4 — a clear "no" ends the conversation cleanly, no further activity.
Case 5 — a direct new product request (no literal "yes") is treated as an
  implicit yes and starts the new cycle immediately.
Case 6 — full multi-product session: CloudRest Sleeping Pad (primary only)
  -> continue shopping -> TrailChef Portable Stove (accept) -> continue
  shopping -> no. Confirms 2 separate orders, 2 separate transaction_ids,
  both in the Audit Log and both reflected in MetricsService (the same
  arithmetic /stats reads from).

Part B continued — Entry 10 (bug found in live testing)
"Nothing" at AWAITING_CONTINUE_SHOPPING wasn't in the negative-recognition
set, so it fell through to being treated as an implicit new product
request (recommend("Nothing")), which no-matched and left the session in
a state indistinguishable from a fresh/finished one instead of a clean
decline. Fixed with a dedicated, wider negative-phrase set scoped to this
one state (_CONTINUE_SHOPPING_NEGATIVE_PHRASES in adapter.py).
Case 7 — expanded negatives ("nothing", "nope", "that's all", "bye", and
  more) all correctly end the session cleanly, same as an explicit "no".
Case 8 — the reverse isn't broken: a genuine new request ("yes, show me
  tents", or a bare product mention) still correctly starts a fresh
  recommend() cycle, not misclassified as a decline.
Case 9 — a genuinely ambiguous reply still re-asks rather than resetting.

Run with: python3 scripts/test_quantity_ask_and_continue_shopping.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audit.audit_log import get_transaction_trail, new_transaction_id
from app.catalog.seed_data import seed
from app.chat_adapter.adapter import ChatSession, ChatState
from app.metrics.service import MetricsService


def case_1_quantity_ask_triggers_when_unspecified() -> None:
    print("\n########## CASE 1 — quantity ask triggers when not specified ##########")
    session = ChatSession()

    turn1 = session.handle_message(
        "I need a good sleeping bag for winter camping, budget around Rs.3000."
    )
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_QUANTITY, "No quantity stated — should ask before any price"
    assert "How many" in turn1
    transaction_id = session._pending["transaction_id"]

    # An unrecognizable reply must not guess — it should re-ask, not
    # silently default to 1 or advance the state.
    turn2 = session.handle_message("banana")
    print(f"NEXUS (turn 2, unrecognizable): {turn2}")
    assert session.state == ChatState.AWAITING_QUANTITY, "Unrecognizable reply must not advance the state"
    trail = get_transaction_trail(transaction_id)
    assert any(e["event_type"] == "quantity_unclear" for e in trail), "Unclear quantity reply should be logged"

    # A recognizable natural-language reply should now proceed correctly.
    turn3 = session.handle_message("two please")
    print(f"NEXUS (turn 3, 'two please'): {turn3}")
    assert session.state == ChatState.AWAITING_CONFIRMATION
    assert session._pending["quantity"] == 2, "Should have parsed 'two please' as quantity=2"
    expected_primary_only = session._pending["primary"]["price_paise"] * 2
    assert session._pending["primary_only_amount_paise"] == expected_primary_only

    print("Confirmed: quantity ask triggers on an unspecified request, rejects gibberish, accepts natural phrasing.")


def case_2_quantity_ask_skipped_when_specified() -> None:
    print("\n\n########## CASE 2 — quantity ask skipped when quantity was already stated ##########")
    session = ChatSession()

    turn1 = session.handle_message("I want exactly 2 CloudRest Sleeping Pads, nothing else.")
    print(f"NEXUS (turn 1): {turn1}")
    assert session.state == ChatState.AWAITING_CONFIRMATION, "Explicit quantity should skip AWAITING_QUANTITY entirely"
    assert session._pending["quantity"] == 2
    transaction_id = session._pending["transaction_id"]

    trail = get_transaction_trail(transaction_id)
    event_types = [e["event_type"] for e in trail]
    assert "quantity_unclear" not in event_types, "No quantity-ask turn should have happened at all"

    turn2 = session.handle_message("yes")
    print(f"NEXUS (turn 2): {turn2}")
    assert "Order placed" in turn2

    print("Confirmed: an explicit quantity in the original request skips the quantity-ask state entirely.")


def case_3_continue_shopping_yes_new_independent_order() -> None:
    print("\n\n########## CASE 3 — continue shopping 'yes' starts a brand new, independent order ##########")
    session = ChatSession()

    session.handle_message("I want exactly 1 CloudRest Sleeping Pad, nothing else.")
    turn2 = session.handle_message("yes")
    print(f"NEXUS (order 1 placed): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    assert "Order placed" in turn2
    first_transaction_id = session.last_transaction_id

    turn3 = session.handle_message("yes")
    print(f"NEXUS (continue shopping, bare yes): {turn3}")
    assert session.state == ChatState.AWAITING_REQUEST, "Bare 'yes' should prompt for the new request, not guess one"

    turn4 = session.handle_message("I want exactly 1 CloudRest Sleeping Pad, nothing else.")
    print(f"NEXUS (second request): {turn4}")
    second_transaction_id = session._pending["transaction_id"]
    assert second_transaction_id != first_transaction_id, "Second cycle must get its own, distinct transaction_id"

    turn5 = session.handle_message("yes")
    print(f"NEXUS (order 2 placed): {turn5}")
    assert "Order placed" in turn5
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING

    trail_1 = get_transaction_trail(first_transaction_id)
    trail_2 = get_transaction_trail(second_transaction_id)
    assert any(e["event_type"] == "gate_check" for e in trail_1)
    assert any(e["event_type"] == "gate_check" for e in trail_2)
    assert any(e["event_type"] == "order_created" for e in trail_1)
    assert any(e["event_type"] == "order_created" for e in trail_2)
    assert all(e["source"] == "chat" for e in trail_1 + trail_2)

    session.handle_message("no")
    assert session.state == ChatState.DONE

    print(
        "Confirmed: 'yes' at continue-shopping starts a fully independent second order — its own "
        "transaction_id, its own gate_check, its own order_created, never bundled with the first."
    )


def case_4_continue_shopping_no_ends_cleanly() -> None:
    print("\n\n########## CASE 4 — continue shopping 'no' ends cleanly ##########")
    session = ChatSession()

    session.handle_message("I want exactly 1 CloudRest Sleeping Pad, nothing else.")
    turn2 = session.handle_message("yes")
    print(f"NEXUS (order placed): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING

    turn3 = session.handle_message("no")
    print(f"NEXUS (turn 3): {turn3}")
    assert session.state == ChatState.DONE
    assert session._pending is None

    print("Confirmed: 'no' at continue-shopping ends the conversation cleanly, no further activity.")


def case_5_continue_shopping_implicit_yes_direct_request() -> None:
    print("\n\n########## CASE 5 — implicit yes via a direct new product request ##########")
    session = ChatSession()

    session.handle_message("I want exactly 1 CloudRest Sleeping Pad, nothing else.")
    turn2 = session.handle_message("no")  # decline the first order outright
    print(f"NEXUS (declined): {turn2}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    first_transaction_id = session.last_transaction_id

    # Not a bare "yes" — a direct new request. Should be treated as an
    # implicit yes and start a fresh cycle immediately, no extra prompt.
    turn3 = session.handle_message("a tent under Rs.9000")
    print(f"NEXUS (implicit yes via new request): {turn3}")
    assert session.state in (ChatState.AWAITING_QUANTITY, ChatState.AWAITING_CONFIRMATION, ChatState.DONE), (
        "Implicit yes should hand straight off into a fresh recommend() cycle, not stay stuck asking again"
    )
    assert session.last_transaction_id != first_transaction_id, "The implicit-yes cycle must get its own transaction_id"

    trail = get_transaction_trail(session.last_transaction_id)
    assert any(e["event_type"] == "recommendation" for e in trail), "A real fresh recommend() cycle must have run"

    print("Confirmed: a direct new request at continue-shopping is treated as an implicit yes, starting a fresh cycle.")


def case_6_multi_product_session_two_orders_in_stats() -> None:
    print("\n\n########## CASE 6 — multi-product session: 2 orders, 2 transaction_ids, both in Stats ##########")

    before = MetricsService.get_summary()
    orders_before = before["total_orders"]

    session = ChatSession()

    # Product 1 — CloudRest Sleeping Pad, accept primary only if an upsell
    # is offered (retry with fresh attempts of the SAME session's first
    # turn is not meaningful mid-session, so just accept whatever the model
    # offers: primary-only if there's an upsell, full otherwise — either
    # way this is one complete, independently-gated order).
    turn1 = session.handle_message("Tell me about the CloudRest Sleeping Pad")
    print(f"NEXUS (turn 1): {turn1}")
    if session.state == ChatState.AWAITING_QUANTITY:
        turn1 = session.handle_message("1")
        print(f"NEXUS (quantity answered): {turn1}")
    assert session.state == ChatState.AWAITING_CONFIRMATION
    has_upsell = session._pending["upsell"] is not None
    confirm_reply = "primary only" if has_upsell else "yes"

    turn2 = session.handle_message(confirm_reply)
    print(f"NEXUS (order 1, reply={confirm_reply!r}): {turn2}")
    assert "Order placed" in turn2, "Order 1 should place successfully (CloudRest Sleeping Pad is well under the Gate bound)"
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    transaction_id_1 = session.last_transaction_id

    # Continue shopping.
    turn3 = session.handle_message("yes")
    print(f"NEXUS (continue shopping): {turn3}")
    assert session.state == ChatState.AWAITING_REQUEST

    # Product 2 — TrailChef Portable Stove, accept in full.
    turn4 = session.handle_message("Tell me about the TrailChef Portable Stove")
    print(f"NEXUS (turn 4): {turn4}")
    if session.state == ChatState.AWAITING_QUANTITY:
        turn4 = session.handle_message("1")
        print(f"NEXUS (quantity answered): {turn4}")
    assert session.state == ChatState.AWAITING_CONFIRMATION
    transaction_id_2 = session._pending["transaction_id"]
    assert transaction_id_2 != transaction_id_1, "Second product must be a distinct, independent transaction"
    # Same conditional accept as product 1: TrailChef Portable Stove alone
    # (Rs.1,799) is safely under the Gate bound, but if the model offers a
    # pricier upsell alongside it, the FULL bundle might exceed Rs.5,000 —
    # accepting primary-only when there's an upsell keeps this test's
    # "should approve" premise reliable without weakening the Gate re-check
    # it's actually exercising.
    has_upsell_2 = session._pending["upsell"] is not None
    confirm_reply_2 = "primary only" if has_upsell_2 else "yes"

    turn5 = session.handle_message(confirm_reply_2)
    print(f"NEXUS (order 2, reply={confirm_reply_2!r}): {turn5}")
    assert "Order placed" in turn5, "Order 2 should place successfully (TrailChef Portable Stove is under the Gate bound)"
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING

    turn6 = session.handle_message("no")
    print(f"NEXUS (done shopping): {turn6}")
    assert session.state == ChatState.DONE

    trail_1 = get_transaction_trail(transaction_id_1)
    trail_2 = get_transaction_trail(transaction_id_2)
    assert sum(1 for e in trail_1 if e["event_type"] == "order_created") == 1
    assert sum(1 for e in trail_2 if e["event_type"] == "order_created") == 1
    assert sum(1 for e in trail_1 if e["event_type"] == "gate_check") == 1
    assert sum(1 for e in trail_2 if e["event_type"] == "gate_check") == 1
    assert all(e["source"] == "chat" for e in trail_1 + trail_2)

    after = MetricsService.get_summary()
    orders_after = after["total_orders"]
    assert orders_after == orders_before + 2, (
        f"Stats should reflect exactly 2 new orders from this session; "
        f"before={orders_before}, after={orders_after}"
    )
    print(f"MetricsService.get_summary()['total_orders']: {orders_before} -> {orders_after}")

    print(
        "Confirmed: a 2-product shopping session produces 2 fully independent, fully audited orders "
        "under 2 distinct transaction_ids, and MetricsService (the same arithmetic /stats reads) "
        "correctly counts both."
    )


def _place_one_order_and_reach_continue_shopping() -> ChatSession:
    """Real, end-to-end setup: a fresh session that has just placed one
    order (via a genuine recommend() -> confirm -> Gate -> order cycle) and
    is sitting at AWAITING_CONTINUE_SHOPPING. Used where the case actually
    needs a real LLM cycle (Case 8's own new-request calls).
    """
    session = ChatSession()
    session.handle_message("I want exactly 1 CloudRest Sleeping Pad, nothing else.")
    turn = session.handle_message("yes")
    assert "Order placed" in turn
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING
    return session


def _reach_continue_shopping_synthetically() -> ChatSession:
    """Put a ChatSession directly into AWAITING_CONTINUE_SHOPPING without
    spending a real LLM call. _handle_continue_shopping()'s own decision
    logic (Cases 7 and 9 below) only looks at self.state/self._pending/
    self.last_transaction_id — it doesn't care how the session got there.
    How a session actually ARRIVES at this state (a real order placed,
    declined, or Gate-rejected) is already covered end-to-end with real
    recommend()/Gate/order calls elsewhere (Cases 3, 4, 6, and the rest of
    the regression suite), so re-proving that here for every phrase under
    test would just be redundant, expensive LLM spend.
    """
    session = ChatSession()
    session.state = ChatState.AWAITING_CONTINUE_SHOPPING
    session._pending = None
    session.last_transaction_id = new_transaction_id()
    return session


def case_7_continue_shopping_expanded_negatives_end_cleanly() -> None:
    print("\n\n########## CASE 7 — Entry 10: expanded negatives all end the session cleanly ##########")

    # "Nothing" is the exact phrase from the reported bug; the rest are the
    # other common decline phrasings called out in the fix request.
    negative_phrases = ["nothing", "nope", "that's all", "bye", "nothing else", "i'm done", "no thanks", "goodbye"]

    for phrase in negative_phrases:
        session = _reach_continue_shopping_synthetically()
        events_before = len(get_transaction_trail(session.last_transaction_id))

        reply = session.handle_message(phrase)
        print(f"NEXUS (reply to {phrase!r}): {reply}")

        assert session.state == ChatState.DONE, f"{phrase!r} should end the session cleanly, not reset/continue"
        assert session._pending is None
        assert "thanks for shopping" in reply.lower(), (
            f"{phrase!r} should get the same clean-end reply as an explicit 'no', got: {reply!r}"
        )
        # No new recommend()/gate_check/order_created activity should have
        # been triggered by what is actually a decline, not a product request.
        events_after = len(get_transaction_trail(session.last_transaction_id))
        assert events_after == events_before, (
            f"{phrase!r} must not trigger any further pipeline activity (no new audit events); "
            f"before={events_before}, after={events_after}"
        )

    print(f"Confirmed: {negative_phrases} all correctly end the session, same as an explicit 'no'.")


def case_8_continue_shopping_real_new_request_still_works() -> None:
    print("\n\n########## CASE 8 — reverse check: a real new request still starts a fresh cycle ##########")

    # 8a — "yes, " prefix + explicit new request.
    session_a = _reach_continue_shopping_synthetically()
    first_transaction_id_a = session_a.last_transaction_id
    reply_a = session_a.handle_message("yes, show me tents")
    print(f"NEXUS ('yes, show me tents'): {reply_a}")
    assert session_a.state in (ChatState.AWAITING_QUANTITY, ChatState.AWAITING_CONFIRMATION, ChatState.DONE), (
        "A real new request must hand off into a fresh recommend() cycle, not get stuck re-asking"
    )
    assert session_a.last_transaction_id != first_transaction_id_a, "Must be a distinct, independent transaction"
    trail_a = get_transaction_trail(session_a.last_transaction_id)
    assert any(e["event_type"] == "recommendation" for e in trail_a), "A real recommend() cycle must have run"

    # 8b — a bare product mention, no "yes" at all.
    session_b = _reach_continue_shopping_synthetically()
    first_transaction_id_b = session_b.last_transaction_id
    reply_b = session_b.handle_message("AlpineGuard Winter Tent")
    print(f"NEXUS ('AlpineGuard Winter Tent'): {reply_b}")
    assert session_b.state in (ChatState.AWAITING_QUANTITY, ChatState.AWAITING_CONFIRMATION, ChatState.DONE)
    assert session_b.last_transaction_id != first_transaction_id_b, "Must be a distinct, independent transaction"
    trail_b = get_transaction_trail(session_b.last_transaction_id)
    assert any(e["event_type"] == "recommendation" for e in trail_b), "A real recommend() cycle must have run"

    print(
        "Confirmed: neither a 'yes, <request>' phrasing nor a bare product mention is misclassified "
        "as a decline — both correctly start a fresh, independent recommend() cycle."
    )


def case_9_continue_shopping_ambiguous_still_reasks() -> None:
    print("\n\n########## CASE 9 — a genuinely ambiguous reply still re-asks, never resets ##########")

    session = _reach_continue_shopping_synthetically()
    transaction_id = session.last_transaction_id

    reply = session.handle_message("maybe")
    print(f"NEXUS (ambiguous 'maybe'): {reply}")
    assert session.state == ChatState.AWAITING_CONTINUE_SHOPPING, "Ambiguous reply must not advance/reset the state"
    assert "anything else" in reply.lower()

    trail = get_transaction_trail(transaction_id)
    assert any(e["event_type"] == "continue_shopping_unclear" for e in trail)
    assert not any(e["event_type"] == "recommendation" for e in trail), "Ambiguous reply must not trigger a new request"

    # Recovery: the session should still work correctly afterward.
    reply2 = session.handle_message("no")
    print(f"NEXUS (now clear 'no'): {reply2}")
    assert session.state == ChatState.DONE

    print("Confirmed: a genuinely ambiguous reply re-asks clearly instead of guessing or resetting.")


def main() -> None:
    seed()
    case_1_quantity_ask_triggers_when_unspecified()
    case_2_quantity_ask_skipped_when_specified()
    case_3_continue_shopping_yes_new_independent_order()
    case_4_continue_shopping_no_ends_cleanly()
    case_5_continue_shopping_implicit_yes_direct_request()
    case_6_multi_product_session_two_orders_in_stats()
    case_7_continue_shopping_expanded_negatives_end_cleanly()
    case_8_continue_shopping_real_new_request_still_works()
    case_9_continue_shopping_ambiguous_still_reasks()
    print("\n\nAll quantity-ask and continue-shopping test cases behaved as expected.")


if __name__ == "__main__":
    main()
