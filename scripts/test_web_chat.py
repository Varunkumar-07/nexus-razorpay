"""Web Chat frontend/backend smoke test.

Purely additive verification on top of Phase 6 — exercises the new HTTP
wrapper (app/web_chat/routes.py) over the existing, unmodified ChatSession,
not the CLI.

Case 1 — full Scenario A flow over HTTP: POST /chat/start -> POST
  /chat/message (request) -> POST /chat/message ("yes") -> GET
  /chat/history -> confirm it matches what actually happened, and that the
  audit trail is tagged source="chat" throughout, exactly as the CLI path.

Case 2 — refresh simulation: start a session, send one message, then fetch
  /chat/history for that session_id as if the page had just reloaded,
  confirm the prior message is still there.

Case 3 — small talk ("hi") gets a friendly reply, never reaches
  recommend().

Case 4 — GET /catalog/all returns all 15 seeded products, correctly
  grouped by category.

Case 5 — browse intent: "show me the products you own, lemme browse" is
  classified as browse_intent (not small_talk, not a failed
  product_request) and returns suggested_action="browse_catalog", both in
  a fresh session AND in a session that has already completed one order
  (regression coverage for the DONE-state classifier gap found in manual
  browser testing — see FAILURE_LOG.md Entry 3).

Case 6 — "Ask about this" message flow: the Catalog page's per-product
  button pre-fills the chat input with "Tell me about the <product name>"
  (verified live in the browser, not here — this is a frontend-only
  navigation/state concern). This case verifies the part that touches the
  backend: once that exact message is actually sent, it flows through the
  unmodified classifier -> recommend() pipeline like any normal chat
  message and produces a real recommendation for that specific product —
  no special-casing, no new route.

Starts the server for real (uvicorn, localhost) and drives it over HTTP,
the same way a browser would.

Run with: python3 scripts/test_web_chat.py
"""

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from app.audit.audit_log import get_transaction_trail
from app.catalog.seed_data import seed

API_BASE_URL = "http://127.0.0.1:8124"


def wait_for_server(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{url}/docs", timeout=2)
            if resp.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise RuntimeError("Server did not become ready in time.")


def case_1_full_scenario_a_over_http() -> None:
    print("\n########## CASE 1 — Scenario A over HTTP (start -> message -> confirm -> history) ##########")

    start_resp = requests.post(f"{API_BASE_URL}/chat/start", timeout=10)
    start_resp.raise_for_status()
    session_id = start_resp.json()["session_id"]
    print(f"Session started: {session_id}")

    msg1 = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={
            "session_id": session_id,
            "message": "I need a good sleeping bag for winter camping, budget around Rs.3000.",
        },
        timeout=30,
    )
    msg1.raise_for_status()
    reply1 = msg1.json()
    print(f"Turn 1 reply: {reply1['reply']}")
    # Arctic Pro Sleeping Bag always comes with the CloudRest Sleeping Pad
    # upsell, so the three-way prompt applies — see FAILURE_LOG.md Entry 6.
    assert "Confirm both items" in reply1["reply"], "Turn 1 should ask for explicit confirmation"
    assert reply1["state"] == "AWAITING_CONFIRMATION"
    transaction_id = reply1["transaction_id"]
    assert transaction_id, "transaction_id should be present after a recommendation"

    msg2 = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={"session_id": session_id, "message": "yes"},
        timeout=30,
    )
    msg2.raise_for_status()
    reply2 = msg2.json()
    print(f"Turn 2 reply: {reply2['reply']}")
    assert "Order placed" in reply2["reply"], "Turn 2 should confirm order placement"
    assert reply2["state"] == "DONE"

    history_resp = requests.get(f"{API_BASE_URL}/chat/history/{session_id}", timeout=10)
    history_resp.raise_for_status()
    history = history_resp.json()
    print(f"History has {len(history)} entries.")
    assert len(history) == 4, "Expect 2 user turns + 2 agent replies"
    assert history[0]["role"] == "user" and "sleeping bag" in history[0]["text"]
    assert history[1]["role"] == "agent" and "Confirm both items" in history[1]["text"]
    assert history[2]["role"] == "user" and history[2]["text"] == "yes"
    assert history[3]["role"] == "agent" and "Order placed" in history[3]["text"]

    trail = get_transaction_trail(transaction_id)
    assert trail, "Audit trail should exist for this transaction"
    assert all(e["source"] == "chat" for e in trail), "All events must be tagged source=chat"
    assert any(e["event_type"] == "order_created" for e in trail)
    print("Confirmed: HTTP flow matches the CLI flow exactly — same ChatSession, same Gate, source=chat throughout.")


def case_2_refresh_simulation() -> None:
    print("\n\n########## CASE 2 — refresh simulation (history survives a simulated page reload) ##########")

    start_resp = requests.post(f"{API_BASE_URL}/chat/start", timeout=10)
    start_resp.raise_for_status()
    session_id = start_resp.json()["session_id"]
    print(f"Session started: {session_id}")

    msg_resp = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={
            "session_id": session_id,
            "message": "I need a good sleeping bag for winter camping, budget around Rs.3000.",
        },
        timeout=30,
    )
    msg_resp.raise_for_status()
    print(f"Sent one message, got: {msg_resp.json()['reply'][:60]}...")

    # Simulate a page refresh: a fresh "browser" only knows the session_id
    # (as it would from the cookie) and re-fetches history from scratch.
    history_resp = requests.get(f"{API_BASE_URL}/chat/history/{session_id}", timeout=10)
    history_resp.raise_for_status()
    history = history_resp.json()
    print(f"History after simulated refresh: {len(history)} entries.")
    assert len(history) == 2, "Expect the user's message + the agent's reply to have survived"
    assert history[0]["role"] == "user" and "sleeping bag" in history[0]["text"]
    assert history[1]["role"] == "agent"
    print("Confirmed: prior message is still present after a simulated page refresh.")


def case_3_small_talk_greeting() -> None:
    print("\n\n########## CASE 3 — small talk ('hi') gets a friendly reply, not a forced recommendation ##########")

    start_resp = requests.post(f"{API_BASE_URL}/chat/start", timeout=10)
    start_resp.raise_for_status()
    session_id = start_resp.json()["session_id"]
    print(f"Session started: {session_id}")

    msg_resp = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={"session_id": session_id, "message": "hi"},
        timeout=30,
    )
    msg_resp.raise_for_status()
    reply = msg_resp.json()
    print(f"Reply to 'hi': {reply['reply']}")
    assert reply["state"] == "AWAITING_REQUEST", "Small talk should not advance the ChatSession state"
    assert reply["transaction_id"] is None, "Small talk must not trigger a recommendation (no transaction_id)"
    assert "NEXUS shopping assistant" in reply["reply"], "Should get the friendly canned greeting"
    assert "no recommendation" not in reply["reply"].lower()

    # A real request afterward, in the same session, must still work exactly
    # as before — proves the classifier doesn't interfere with Scenario A.
    followup = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={
            "session_id": session_id,
            "message": "I need a good sleeping bag for winter camping, budget around Rs.3000.",
        },
        timeout=30,
    )
    followup.raise_for_status()
    followup_reply = followup.json()
    print(f"Follow-up request reply: {followup_reply['reply']}")
    assert "Confirm both items" in followup_reply["reply"], "A real request after small talk should work normally"
    assert followup_reply["state"] == "AWAITING_CONFIRMATION"

    history_resp = requests.get(f"{API_BASE_URL}/chat/history/{session_id}", timeout=10)
    history_resp.raise_for_status()
    history = history_resp.json()
    assert len(history) == 4, "Expect: hi, greeting reply, real request, recommendation reply"
    print(
        "Confirmed: small talk gets a friendly reply without touching the recommendation pipeline, "
        "and a real request afterward in the same session still works normally."
    )


def case_4_catalog_all() -> None:
    print("\n\n########## CASE 4 — GET /catalog/all returns all 15 products, correctly grouped ##########")

    resp = requests.get(f"{API_BASE_URL}/catalog/all", timeout=10)
    resp.raise_for_status()
    grouped = resp.json()

    total = sum(len(products) for products in grouped.values())
    print(f"Categories: {sorted(grouped.keys())}")
    print(f"Total products: {total}")

    expected_categories = {"sleeping_bags", "tents", "backpacks", "cooking_gear", "accessories"}
    assert set(grouped.keys()) == expected_categories, f"Unexpected category set: {grouped.keys()}"
    assert total == 15, f"Expected 15 total products, got {total}"

    for category, products in grouped.items():
        for product in products:
            assert product["category"] == category, "Each product must be filed under its own category"
            assert isinstance(product["price_paise"], int)
            assert product["name"] and product["spec"]

    # Spot-check a known product, matching Phase 1's seed data.
    sleeping_bags = grouped["sleeping_bags"]
    arctic_pro = next((p for p in sleeping_bags if p["id"] == 1), None)
    assert arctic_pro is not None, "Arctic Pro Sleeping Bag (id=1) should be present"
    assert arctic_pro["price_paise"] == 279_900

    print("Confirmed: /catalog/all returns all 15 seeded products, correctly grouped by category.")


BROWSE_MESSAGE = "show me the products you own, lemme browse"


def case_5_browse_intent() -> None:
    print("\n\n########## CASE 5 — browse intent gets suggested_action='browse_catalog' ##########")

    start_resp = requests.post(f"{API_BASE_URL}/chat/start", timeout=10)
    start_resp.raise_for_status()
    session_id = start_resp.json()["session_id"]
    print(f"Session started: {session_id}")

    # 5a — fresh session (AWAITING_REQUEST).
    resp_a = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={"session_id": session_id, "message": BROWSE_MESSAGE},
        timeout=30,
    )
    resp_a.raise_for_status()
    data_a = resp_a.json()
    print(f"Fresh-session reply: {data_a['reply']}")
    assert data_a["suggested_action"] == "browse_catalog", "Should classify as browse_intent, not product_request"
    assert data_a["state"] == "AWAITING_REQUEST", "Browse intent should not advance the ChatSession state"

    # Complete one order in the same session, so it reaches DONE state.
    r1 = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={
            "session_id": session_id,
            "message": "I need a good sleeping bag for winter camping, budget around Rs.3000.",
        },
        timeout=30,
    )
    r1.raise_for_status()
    assert "Confirm both items" in r1.json()["reply"]

    r2 = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={"session_id": session_id, "message": "yes"},
        timeout=30,
    )
    r2.raise_for_status()
    assert "Order placed" in r2.json()["reply"]
    assert r2.json()["state"] == "DONE"

    # 5b — same session, now in DONE state (regression case for Entry 3:
    # the classifier gate used to only fire in AWAITING_REQUEST and
    # silently skipped DONE, even though ChatSession itself treats DONE
    # as a fresh request too).
    resp_b = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={"session_id": session_id, "message": BROWSE_MESSAGE},
        timeout=30,
    )
    resp_b.raise_for_status()
    data_b = resp_b.json()
    print(f"Post-order (DONE state) reply: {data_b['reply']}")
    assert data_b["suggested_action"] == "browse_catalog", (
        "Browse intent must still be classified correctly after a completed order (DONE state)"
    )

    print("Confirmed: browse intent is classified correctly both in a fresh session and after a completed order.")


def case_6_ask_about_this() -> None:
    print("\n\n########## CASE 6 — 'Ask about this' message flows through the unmodified pipeline ##########")

    start_resp = requests.post(f"{API_BASE_URL}/chat/start", timeout=10)
    start_resp.raise_for_status()
    session_id = start_resp.json()["session_id"]
    print(f"Session started: {session_id}")

    # Exactly what CatalogView.jsx composes for the Arctic Pro Sleeping Bag
    # card — a plain chat message, sent through the same POST /chat/message
    # endpoint as anything the buyer types themselves.
    prefill_message = "Tell me about the Arctic Pro Sleeping Bag"
    resp = requests.post(
        f"{API_BASE_URL}/chat/message",
        json={"session_id": session_id, "message": prefill_message},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    print(f"Reply: {data['reply']}")

    assert data["suggested_action"] is None, "Should be classified as a product request, not browse/small-talk"
    assert data["state"] == "AWAITING_CONFIRMATION", "Naming a specific product should produce a real recommendation"
    assert "Arctic Pro Sleeping Bag" in data["reply"], "Recommendation should be for the product actually named"
    assert "Confirm both items" in data["reply"]

    transaction_id = data["transaction_id"]
    trail = get_transaction_trail(transaction_id)
    recommendation_events = [e for e in trail if e["event_type"] == "recommendation"]
    assert len(recommendation_events) == 1, "Expect exactly one recommendation event"
    assert recommendation_events[0]["details"]["primary_product_id"] == 1, (
        "Recommended primary should be the Arctic Pro Sleeping Bag (id=1), matching what was asked about"
    )
    assert recommendation_events[0]["details"]["request"] == prefill_message, (
        "The audit log should show the exact composed message, proving no special-casing happened"
    )

    print(
        "Confirmed: the 'Ask about this' message runs through the exact same classifier -> recommend() "
        "pipeline as any typed message, and correctly recommends the specific product it named."
    )


def main() -> None:
    seed()

    print(f"Starting NEXUS server on {API_BASE_URL} ...")
    server = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.agent_api.main:app",
            "--host", "127.0.0.1", "--port", "8124", "--log-level", "warning",
        ],
        cwd=str(PROJECT_ROOT),
    )
    try:
        wait_for_server(API_BASE_URL)
        print("Server is up.\n")

        case_1_full_scenario_a_over_http()
        case_2_refresh_simulation()
        case_3_small_talk_greeting()
        case_4_catalog_all()
        case_5_browse_intent()
        case_6_ask_about_this()

        print("\n\nAll web chat test cases behaved as expected.")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
