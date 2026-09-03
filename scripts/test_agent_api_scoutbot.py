"""Phase 7, Part C — verification.

Starts the NEXUS Agent API for real (uvicorn, localhost), then runs
ScoutBot against it over real HTTP twice:

  Case 1 — "Buy one tent under Rs.5000" -> best fit is within the Rs.5,000
           gate bound -> expect a real Razorpay test-mode order.

  Case 2 — "Buy one tent under Rs.9000" -> ScoutBot's own budget allows it,
           and the best-fit product (AlpineGuard Winter Tent, Rs.8999) is
           found and recommended — but Rs.8999 exceeds the Gate's fixed
           Rs.5,000 auto-approval bound. The Gate must refuse, proving both
           adapters are governed by the exact same Gate, independent of
           what the calling agent considers its own budget.

  Case 3 — Tampered POST /order (underpay attempt): recommend a tent under
           Rs.5000 (real price Rs.4,599 — the StormShield 2-Person Tent),
           then call /order directly with amount_paise lied down to Rs.1.
           The order must still be approved and charged at the real
           Rs.4,599 — proving the server ignores the client's amount_paise
           and uses what /recommend actually produced.

  Case 4 — Tampered POST /order (gate-bypass attempt): recommend a tent
           under Rs.9000 (real price Rs.8,999 — over the Gate's Rs.5,000
           bound), then call /order directly with amount_paise lied down
           to Rs.1, well under the bound. The Gate must still refuse,
           proving a caller cannot talk their way past the Rs.5,000 bound
           by simply claiming a smaller amount than what was recommended.

  Case 5 — POST /order with a transaction_id that never went through
           /recommend. Must be rejected with 404, not silently accepted.

Prints the full audit trail for each transaction, confirming every event
is tagged source="agent".

Run with: python3 scripts/test_agent_api_scoutbot.py
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
from scoutbot.scoutbot import buy

API_BASE_URL = "http://127.0.0.1:8123"


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
    raise RuntimeError("Agent API did not become ready in time.")


def print_trail(transaction_id: str) -> list:
    print(f"\n=== Full audit trail for transaction {transaction_id} ===")
    trail = get_transaction_trail(transaction_id)
    for event in trail:
        print(
            f"\n[{event['id']}] {event['timestamp']} | source={event['source']} "
            f"| event_type={event['event_type']}"
        )
        print(f"    details: {event['details']}")
    return trail


def main() -> None:
    seed()

    print(f"Starting NEXUS Agent API on {API_BASE_URL} ...")
    server = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.agent_api.main:app",
            "--host", "127.0.0.1", "--port", "8123", "--log-level", "warning",
        ],
        cwd=str(PROJECT_ROOT),
    )
    try:
        wait_for_server(API_BASE_URL)
        print("Agent API is up.\n")

        print("########## CASE 1 — tent under Rs.5000 (should SUCCEED) ##########")
        result_1 = buy("Buy one tent under Rs.5000 from Northlight Outdoors.", API_BASE_URL)
        assert result_1["success"] is True, "Case 1 should have resulted in a real order"
        trail_1 = print_trail(result_1["transaction_id"])
        assert all(e["source"] == "agent" for e in trail_1), "All events must be tagged source=agent"
        assert any(e["event_type"] == "order_created" for e in trail_1), "order_created event expected"
        print("\nConfirmed: real order created, entire trail tagged source=agent.\n")

        print("\n########## CASE 2 — tent under Rs.9000 (exceeds Rs.5000 gate bound) ##########")
        result_2 = buy("Buy one tent under Rs.9000 from Northlight Outdoors.", API_BASE_URL)
        assert result_2["success"] is False, "Case 2 should have been refused by the Gate"
        trail_2 = print_trail(result_2["transaction_id"])
        assert all(e["source"] == "agent" for e in trail_2), "All events must be tagged source=agent"
        assert not any(
            e["event_type"] == "order_created" for e in trail_2
        ), "No order_created event should exist for a Gate-refused transaction"
        assert any(
            e["event_type"] == "gate_check" and e["details"]["approved"] is False for e in trail_2
        ), "A rejected gate_check event is expected"
        print("\nConfirmed: Gate refused the over-bound order — same Gate logic as the chat path.")

        print("\n########## CASE 3 — tampered /order, underpay attempt (should charge the REAL amount) ##########")
        recommend_3 = requests.post(
            f"{API_BASE_URL}/recommend",
            json={"category": "tents", "max_price_paise": 500000, "keywords": None},
            timeout=15,
        )
        recommend_3.raise_for_status()
        rec_3 = recommend_3.json()
        real_amount_3 = rec_3["primary"]["price_paise"]
        print(f"ScoutBot test: /recommend picked {rec_3['primary']['name']} at Rs.{real_amount_3 / 100:.2f}")
        print("Test: calling /order with amount_paise tampered down to Rs.1 ...")
        order_3 = requests.post(
            f"{API_BASE_URL}/order",
            json={
                "transaction_id": rec_3["transaction_id"],
                "amount_paise": 100,  # lied: real price is real_amount_3, not Rs.1
                "confirmed": True,
                "reasoning": "Attempting to underpay by lying about amount_paise.",
            },
            timeout=15,
        )
        order_3.raise_for_status()
        result_3 = order_3.json()
        assert result_3["approved"] is True, "Case 3 order should be approved (real amount is under the bound)"
        assert result_3["order"] is not None, "Case 3 should produce a real Razorpay order"
        assert result_3["order"]["amount"] == real_amount_3, (
            f"Case 3 was charged {result_3['order']['amount']} paise, expected the real "
            f"recommended amount {real_amount_3} paise — the tampered amount_paise must be ignored"
        )
        trail_3 = print_trail(rec_3["transaction_id"])
        gate_checks_3 = [e for e in trail_3 if e["event_type"] == "gate_check"]
        assert gate_checks_3 and gate_checks_3[0]["details"]["amount_paise"] == real_amount_3, (
            "Case 3's gate_check event must record the real amount, not the tampered one"
        )
        print(f"\nConfirmed: charged Rs.{result_3['order']['amount'] / 100:.2f} (real price), tampered amount_paise=Rs.1 had zero effect.")

        print("\n########## CASE 4 — tampered /order, gate-bypass attempt (should still be REFUSED) ##########")
        recommend_4 = requests.post(
            f"{API_BASE_URL}/recommend",
            json={"category": "tents", "max_price_paise": 900000, "keywords": None},
            timeout=15,
        )
        recommend_4.raise_for_status()
        rec_4 = recommend_4.json()
        real_amount_4 = rec_4["primary"]["price_paise"]
        assert real_amount_4 > 500000, "Case 4 requires a recommendation over the Rs.5,000 bound to be meaningful"
        print(f"ScoutBot test: /recommend picked {rec_4['primary']['name']} at Rs.{real_amount_4 / 100:.2f} (over the bound)")
        print("Test: calling /order with amount_paise tampered down to Rs.1, hoping to sneak past the Gate ...")
        order_4 = requests.post(
            f"{API_BASE_URL}/order",
            json={
                "transaction_id": rec_4["transaction_id"],
                "amount_paise": 100,  # lied: hoping the Gate checks this instead of the real amount
                "confirmed": True,
                "reasoning": "Attempting to bypass the Rs.5,000 gate bound by lying about amount_paise.",
            },
            timeout=15,
        )
        order_4.raise_for_status()
        result_4 = order_4.json()
        assert result_4["approved"] is False, "Case 4 must be refused — real amount exceeds the Gate bound"
        assert result_4["order"] is None, "Case 4 must not create a Razorpay order"
        trail_4 = print_trail(rec_4["transaction_id"])
        assert not any(e["event_type"] == "order_created" for e in trail_4), "No order_created event expected for Case 4"
        gate_checks_4 = [e for e in trail_4 if e["event_type"] == "gate_check"]
        assert gate_checks_4 and gate_checks_4[0]["details"]["amount_paise"] == real_amount_4, (
            "Case 4's gate_check event must record the real amount, not the tampered one"
        )
        print("\nConfirmed: tampering amount_paise down does not bypass the Rs.5,000 Gate bound.")

        print("\n########## CASE 5 — /order with an unknown transaction_id (should be REJECTED, 404) ##########")
        order_5 = requests.post(
            f"{API_BASE_URL}/order",
            json={
                "transaction_id": "no-such-transaction-id",
                "amount_paise": 100,
                "confirmed": True,
                "reasoning": "This transaction_id never went through /recommend.",
            },
            timeout=15,
        )
        assert order_5.status_code == 404, f"Case 5 expected 404, got {order_5.status_code}"
        print(f"\nConfirmed: unknown transaction_id rejected with {order_5.status_code}: {order_5.json()['detail']}")

        print("\n\nAll Phase 7 test cases behaved as expected.")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
