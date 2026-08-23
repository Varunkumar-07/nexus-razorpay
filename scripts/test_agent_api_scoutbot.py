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

        print("\n\nAll Phase 7 test cases behaved as expected.")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
