"""View the full audit trail for one transaction (Phase 9 convenience tool).

Every phase's test script already prints a transaction's audit trail as
part of its own output; this is the same lookup exposed as a standalone
tool, for looking up a transaction_id after the fact (e.g. one printed by
scripts/chat_cli.py or by scoutbot/scoutbot.py).

Run with: python3 scripts/view_audit_trail.py <transaction_id>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audit.audit_log import get_transaction_trail


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/view_audit_trail.py <transaction_id>")
        sys.exit(1)

    transaction_id = sys.argv[1]
    trail = get_transaction_trail(transaction_id)

    if not trail:
        print(f"No events found for transaction_id={transaction_id!r}.")
        sys.exit(1)

    print(f"=== Audit trail for transaction {transaction_id} ({len(trail)} event(s)) ===")
    for event in trail:
        print(
            f"\n[{event['id']}] {event['timestamp']} | source={event['source']} "
            f"| event_type={event['event_type']}"
        )
        print(f"    details: {event['details']}")


if __name__ == "__main__":
    main()
