"""Regression test for scripts/reset_demo_state.py.

Seeds a handful of real orders/rejections through the actual pipeline —
Gate + Razorpay order creation, in-process, source="agent" — so there's
real data to wipe, confirms the script refuses to run without
confirmation, then confirms --yes leaves the system clean: audit log
empty, catalog still exactly 15 products, and the live GET
/metrics/summary endpoint reports zero orders and zero revenue.

Run with: python3 scripts/test_reset_demo_state.py
"""

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from app.audit.audit_log import get_events_by_type, log_event, new_transaction_id
from app.catalog.seed_data import seed
from app.catalog.service import filter_by_max_price
from app.gate.gate import check_gate
from app.razorpay_integration.orders import create_order

RESET_SCRIPT = PROJECT_ROOT / "scripts" / "reset_demo_state.py"
API_BASE_URL = "http://127.0.0.1:8126"


def seed_fake_transactions() -> None:
    """Push a real order, an over-bound rejection, and a decline through
    the actual pipeline, so the reset has real rows to clear."""
    tid = new_transaction_id()
    gate_result = check_gate(
        amount_paise=14_900,
        confirmed=True,
        reasoning="reset_demo_state regression test: fake order to be wiped.",
        transaction_id=tid,
        source="agent",
    )
    assert gate_result["approved"] is True
    order_result = create_order(gate_result, transaction_id=tid, source="agent")
    assert order_result["success"] is True, f"Razorpay order creation failed: {order_result}"

    check_gate(
        amount_paise=999_900,
        confirmed=True,
        reasoning="reset_demo_state regression test: over-bound rejection to be wiped.",
        transaction_id=new_transaction_id(),
        source="agent",
    )

    log_event(
        transaction_id=new_transaction_id(),
        source="agent",
        event_type="order_declined",
        details={"reason": "reset_demo_state regression test decline"},
    )


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


def case_refuses_without_confirmation() -> None:
    print("### Case 1: refuses to run without confirmation ###")
    seed_fake_transactions()
    before = len(get_events_by_type("order_created"))
    assert before > 0, "seeding must have produced at least one order_created event"

    result = subprocess.run(
        [sys.executable, str(RESET_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        input="no\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(result.stdout)
    assert result.returncode != 0, "declining confirmation must exit non-zero"
    assert "Aborted" in result.stdout

    after = len(get_events_by_type("order_created"))
    assert after == before, "declining confirmation must not touch the audit log"
    print("Confirmed: declining the prompt leaves the audit log untouched.\n")


def case_yes_flag_wipes_everything_and_metrics_zero() -> None:
    print("### Case 2: --yes wipes the audit log, catalog stays at 15, metrics go to zero ###")

    result = subprocess.run(
        [sys.executable, str(RESET_SCRIPT), "--yes"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(result.stdout)
    assert result.returncode == 0, (
        f"reset script should exit 0 on success, got {result.returncode}\n{result.stdout}\n{result.stderr}"
    )
    assert "Traceback" not in result.stdout and "Traceback" not in result.stderr

    for event_type in ("order_created", "order_declined", "gate_check", "recommendation", "confirmation_unclear"):
        remaining = get_events_by_type(event_type)
        assert remaining == [], f"audit log should be empty after reset, found {len(remaining)} '{event_type}' row(s)"

    seed()  # idempotent — confirms no crash even after the reset script's own catalog check
    all_products = filter_by_max_price(10**12)
    assert len(all_products) == 15, f"expected 15 products after reset, found {len(all_products)}"

    print("Starting NEXUS server to check the live /metrics/summary endpoint ...")
    server = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.agent_api.main:app",
            "--host", "127.0.0.1", "--port", "8126", "--log-level", "warning",
        ],
        cwd=str(PROJECT_ROOT),
    )
    try:
        wait_for_server(API_BASE_URL)
        resp = requests.get(f"{API_BASE_URL}/metrics/summary", timeout=10)
        resp.raise_for_status()
        summary = resp.json()
        print(f"  /metrics/summary: {summary}")
        assert summary["total_orders"] == 0, "total_orders should be 0 after reset"
        assert summary["total_revenue_rupees"] == 0, "total_revenue_rupees should be 0 after reset"
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    print(
        "Confirmed: audit log empty, catalog has exactly 15 products, "
        "/metrics/summary reports zero orders and zero revenue.\n"
    )


def main() -> None:
    case_refuses_without_confirmation()
    case_yes_flag_wipes_everything_and_metrics_zero()
    print("All reset_demo_state.py regression cases passed.")


if __name__ == "__main__":
    main()
