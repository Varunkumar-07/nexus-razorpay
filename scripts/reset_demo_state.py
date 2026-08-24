"""Reset demo state — wipe local testing mess before recording a demo.

Clears every row in the Audit Log (the source of the Stats page's numbers,
and the running tally of every test transaction made while building and
testing this app) and confirms the product catalog is still exactly the
15-product seed set. Meant to be run more than once: practice runs, then a
final reset right before recording.

Order logic never decrements product stock — checked directly: no code
path in app/gate, app/razorpay_integration, app/chat_adapter, or
app/agent_api writes to the products table, "stock" only appears there as
a read-only display field. So the catalog only needs to be *verified*
here, not unconditionally rebuilt — this script falls back to a
drop-and-reseed only if that verification ever fails (e.g. the db file
was hand-edited), reusing check_setup.py's own catalog-seed check.

Does NOT touch .env, does NOT touch any code files, and does NOT touch
Razorpay's own test-mode order history — that lives entirely on
Razorpay's side, can't be cleared from here, and doesn't need to be:
those are harmless test orders that never surface anywhere in this app's
own UI once the Audit Log is empty.

Destructive to local data (the audit log), so it always requires explicit
confirmation — either an interactive "type yes" prompt, or --yes for
non-interactive use. Never wipes anything silently.

Usage:
    python3 scripts/reset_demo_state.py            # interactive confirmation
    python3 scripts/reset_demo_state.py --yes       # non-interactive
"""

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.audit.audit_log import init_audit_log
from app.catalog.db import get_connection
from app.catalog.seed_data import seed
from app.metrics.service import MetricsService
from scripts.check_setup import check_catalog_seeded


def confirm(assume_yes: bool) -> bool:
    if assume_yes:
        return True
    print("This will PERMANENTLY delete every row in the local audit log")
    print("(every recorded order, gate check, recommendation, and rejection).")
    reply = input("Type 'yes' to confirm: ").strip().lower()
    return reply == "yes"


def clear_audit_log() -> int:
    """Delete every row from audit_log. Returns the row count before clearing."""
    init_audit_log()
    conn = get_connection()
    try:
        before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        conn.execute("DELETE FROM audit_log")
        try:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'audit_log'")
        except sqlite3.OperationalError:
            pass  # no sqlite_sequence table yet — audit_log has never held a row
        conn.commit()
        return before
    finally:
        conn.close()


def ensure_catalog_clean() -> str:
    """Verify the catalog is the clean 15-product seed set (via
    check_setup.py's own check_catalog_seeded, so this stays in sync with
    what check_setup.py itself considers "seeded"). Rebuild only if that
    verification fails. Returns a short human-readable description."""
    result = check_catalog_seeded()
    if result.passed:
        return "verified intact — 15 products match the seed set (no rebuild needed)"

    conn = get_connection()
    try:
        conn.execute("DROP TABLE IF EXISTS products")
        conn.commit()
    finally:
        conn.close()
    seed()

    result = check_catalog_seeded()
    if not result.passed:
        raise RuntimeError(f"Catalog rebuild failed to reach a clean state: {result.detail}")
    return "was not a clean 15-product set — dropped and re-seeded from scratch"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset NEXUS local demo state (audit log + catalog check).")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt.")
    args = parser.parse_args()

    print("NEXUS demo reset")
    print("=" * 50)

    if not confirm(args.yes):
        print("\nAborted — no confirmation given. Nothing was changed.")
        return 1

    audit_rows_cleared = clear_audit_log()
    catalog_status = ensure_catalog_clean()
    summary = MetricsService.get_summary()

    print(f"\nAudit log:  cleared {audit_rows_cleared} row(s). Now empty.")
    print(f"Catalog:    {catalog_status}.")
    print(
        f"Stats:      /metrics/summary now reports {summary['total_orders']} orders, "
        f"Rs.{summary['total_revenue_paise'] / 100:.2f} revenue."
    )

    if summary["total_orders"] != 0 or summary["total_revenue_paise"] != 0:
        print("\nWARNING: metrics did not reset to zero after clearing the audit log — investigate before recording.")
        return 1

    print("\nDemo state is clean and verified. Ready to record.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
