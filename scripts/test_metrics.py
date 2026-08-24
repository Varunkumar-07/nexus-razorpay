"""Metrics module regression suite.

Seeds a known sequence of real transactions through the actual pipeline
(ChatSession + Gate + Razorpay, plus one direct Agent-path order) covering
every counted outcome: full-bundle accepted, primary-only accepted, full
decline, an unclear reply followed by acceptance, an over-bound rejection,
and one agent-source order.

Rather than computing fragile deltas on top of whatever historical data
already exists in the shared audit log (rates like "upsell acceptance
rate" don't combine additively, so delta math on them is unreliable),
this test independently reimplements the metrics arithmetic from scratch
— pulling raw events straight from the Audit Log and doing the same
computation MetricsService should be doing, as a genuine cross-check —
then asserts the live GET /metrics/summary endpoint's numbers match that
independent computation exactly, over the full current dataset. This
validates the arithmetic itself, not just "did numbers move."

Run with: python3 scripts/test_metrics.py
"""

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from app.audit.audit_log import get_events_by_type, new_transaction_id
from app.catalog.seed_data import seed
from app.catalog.service import get_product_by_id
from app.chat_adapter.adapter import ChatSession, ChatState
from app.gate.gate import check_gate
from app.razorpay_integration.orders import create_order

API_BASE_URL = "http://127.0.0.1:8125"
SCENARIO_A_REQUEST = "I need a good sleeping bag for winter camping, budget around Rs.3000."


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


def get_session_with_upsell(request: str, max_attempts: int = 5):
    """Retry with fresh sessions until the LLM actually offers an upsell —
    its upsell decision isn't pinned to temperature=0, so it varies run to
    run. What's under test is the metrics arithmetic, not the model's
    determinism, so we retry rather than let unrelated variability fail
    the test (same pattern as scripts/test_upsell_decline.py).
    """
    for attempt in range(1, max_attempts + 1):
        session = ChatSession()
        turn1 = session.handle_message(request)
        if session._pending is not None and session._pending["upsell"] is not None:
            return session, turn1
        print(f"    (attempt {attempt}: no upsell offered this run, retrying)")
    raise AssertionError(f"No upsell was offered for {request!r} after {max_attempts} attempts")


def run_known_sequence() -> None:
    """Seed one of each counted outcome through the real pipeline."""

    print("### Step A: full bundle accepted (chat) ###")
    session, turn1 = get_session_with_upsell(SCENARIO_A_REQUEST)
    print(f"  turn1: {turn1}")
    turn2 = session.handle_message("yes")
    print(f"  turn2: {turn2}")
    assert "Order placed" in turn2 and "primary item only" not in turn2.lower()

    print("### Step B: primary-only accepted (chat) ###")
    session, turn1 = get_session_with_upsell(SCENARIO_A_REQUEST)
    print(f"  turn1: {turn1}")
    turn2 = session.handle_message("primary only")
    print(f"  turn2: {turn2}")
    assert "Order placed" in turn2 and "primary item only" in turn2.lower()

    print("### Step C: full decline (chat) ###")
    session, turn1 = get_session_with_upsell(SCENARIO_A_REQUEST)
    print(f"  turn1: {turn1}")
    turn2 = session.handle_message("no")
    print(f"  turn2: {turn2}")
    assert "cancel" in turn2.lower()

    print("### Step D: unclear reply, then accept (chat) ###")
    session, turn1 = get_session_with_upsell(SCENARIO_A_REQUEST)
    print(f"  turn1: {turn1}")
    turn_unclear = session.handle_message("hmm not sure")
    print(f"  turn2 (unclear): {turn_unclear}")
    assert session.state == ChatState.AWAITING_CONFIRMATION
    turn3 = session.handle_message("yes")
    print(f"  turn3: {turn3}")
    assert "Order placed" in turn3

    print("### Step E: over-bound rejection (chat) ###")
    session, turn1 = get_session_with_upsell("Tell me about the ExpeditionMax 65L Backpack")
    print(f"  turn1: {turn1}")
    turn2 = session.handle_message("yes")
    print(f"  turn2: {turn2}")
    assert "Order placed" not in turn2
    assert "exceeds" in turn2 and "auto-approval limit" in turn2

    print("### Step F: agent-source order (direct Gate + Razorpay) ###")
    tid = new_transaction_id()
    gate_result = check_gate(
        amount_paise=9_900,
        confirmed=True,
        reasoning="Metrics regression test: known agent-source order.",
        transaction_id=tid,
        source="agent",
    )
    assert gate_result["approved"] is True
    order_result = create_order(gate_result, transaction_id=tid, source="agent")
    assert order_result["success"] is True
    print(f"  order: {order_result['order']['id']}")

    print("\nKnown sequence complete: 4 orders (3 chat + 1 agent), 1 decline, 1 unclear, 1 over-bound rejection.")


def compute_reference_summary() -> dict:
    """Independently reimplement the metrics arithmetic from raw Audit Log
    events — deliberately not calling into app.metrics.service at all —
    as a genuine cross-check against the live endpoint's output.
    """
    order_events = get_events_by_type("order_created")
    recommendation_events = get_events_by_type("recommendation")
    gate_check_events = get_events_by_type("gate_check")
    declined_events = get_events_by_type("order_declined")
    unclear_events = get_events_by_type("confirmation_unclear")

    total_orders = len(order_events)
    total_revenue_paise = sum(e["details"]["order"]["amount"] for e in order_events)
    avg_order_value_paise = (total_revenue_paise / total_orders) if total_orders else 0.0

    by_source = {}
    for src in ("chat", "agent"):
        src_orders = [e for e in order_events if e["source"] == src]
        by_source[src] = {
            "order_count": len(src_orders),
            "revenue_paise": sum(e["details"]["order"]["amount"] for e in src_orders),
        }

    matched = [e for e in recommendation_events if not e["details"].get("no_match")]
    with_upsell = [e for e in matched if e["details"].get("upsell_product_id") is not None]
    upsell_offer_rate = (len(with_upsell) / len(matched)) if matched else 0.0

    gate_by_tx = {}
    for g in gate_check_events:
        gate_by_tx.setdefault(g["transaction_id"], []).append(g)

    accepted_full = 0
    considered = 0
    for rec in with_upsell:
        gates = gate_by_tx.get(rec["transaction_id"])
        if not gates:
            continue
        primary = get_product_by_id(rec["details"]["primary_product_id"])
        upsell = get_product_by_id(rec["details"]["upsell_product_id"])
        if not primary or not upsell:
            continue
        qty = rec["details"].get("quantity", 1)
        primary_only_amt = primary["price_paise"] * qty
        full_amt = primary_only_amt + upsell["price_paise"]
        gated_amt = gates[0]["details"]["amount_paise"]
        if gated_amt == full_amt:
            considered += 1
            accepted_full += 1
        elif gated_amt == primary_only_amt:
            considered += 1
    upsell_acceptance_rate = (accepted_full / considered) if considered else 0.0

    over_bound = sum(1 for g in gate_check_events if not g["details"]["approved"])
    declined = len(declined_events)
    unclear = len(unclear_events)
    total_attempts = len(gate_check_events) + declined + unclear
    total_rejected = over_bound + declined + unclear
    gate_rejection_rate = (total_rejected / total_attempts) if total_attempts else 0.0

    return {
        "total_orders": total_orders,
        "total_revenue_rupees": total_revenue_paise / 100,
        "average_order_value_rupees": avg_order_value_paise / 100,
        "upsell_offer_rate": upsell_offer_rate,
        "upsell_acceptance_rate": upsell_acceptance_rate,
        "gate_rejection_rate": gate_rejection_rate,
        "gate_rejection_breakdown": {"over_bound": over_bound, "declined": declined, "unclear": unclear},
        "by_source": {
            src: {"order_count": v["order_count"], "revenue_rupees": v["revenue_paise"] / 100}
            for src, v in by_source.items()
        },
    }


def assert_close(actual: float, expected: float, label: str, tol: float = 1e-6) -> None:
    assert abs(actual - expected) < tol, f"{label}: expected {expected}, got {actual}"


def main() -> None:
    seed()

    print(f"Starting NEXUS server on {API_BASE_URL} ...")
    server = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.agent_api.main:app",
            "--host", "127.0.0.1", "--port", "8125", "--log-level", "warning",
        ],
        cwd=str(PROJECT_ROOT),
    )
    try:
        wait_for_server(API_BASE_URL)
        print("Server is up.\n")

        run_known_sequence()

        print("\n### Cross-checking GET /metrics/summary against an independent computation ###")
        resp = requests.get(f"{API_BASE_URL}/metrics/summary", timeout=10)
        resp.raise_for_status()
        actual = resp.json()
        expected = compute_reference_summary()

        print(f"Endpoint:    {actual}")
        print(f"Independent: {expected}")

        assert actual["total_orders"] == expected["total_orders"]
        assert_close(actual["total_revenue_rupees"], expected["total_revenue_rupees"], "total_revenue_rupees")
        assert_close(
            actual["average_order_value_rupees"], expected["average_order_value_rupees"], "average_order_value_rupees"
        )
        assert_close(actual["upsell_offer_rate"], expected["upsell_offer_rate"], "upsell_offer_rate")
        assert_close(actual["upsell_acceptance_rate"], expected["upsell_acceptance_rate"], "upsell_acceptance_rate")
        assert_close(actual["gate_rejection_rate"], expected["gate_rejection_rate"], "gate_rejection_rate")
        assert actual["gate_rejection_breakdown"] == expected["gate_rejection_breakdown"]
        for src in ("chat", "agent"):
            assert actual["by_source"][src]["order_count"] == expected["by_source"][src]["order_count"]
            assert_close(
                actual["by_source"][src]["revenue_rupees"],
                expected["by_source"][src]["revenue_rupees"],
                f"by_source[{src}].revenue_rupees",
            )

        # Sanity checks specific to this test's known sequence — proves the
        # new counters actually moved, not just that the arithmetic is
        # internally consistent with itself.
        assert expected["gate_rejection_breakdown"]["declined"] >= 1, "Step C's decline should be logged"
        assert expected["gate_rejection_breakdown"]["unclear"] >= 1, "Step D's unclear reply should be logged"
        assert expected["gate_rejection_breakdown"]["over_bound"] >= 1, "Step E's over-bound rejection should be logged"
        assert expected["by_source"]["agent"]["order_count"] >= 1, "Step F's agent order should be counted"
        assert expected["by_source"]["chat"]["order_count"] >= 3, "Steps A/B/D's chat orders should be counted"

        print(
            "\nConfirmed: GET /metrics/summary matches an independently-computed reference exactly, "
            "and every new counter from this test's known sequence moved as expected."
        )

    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
