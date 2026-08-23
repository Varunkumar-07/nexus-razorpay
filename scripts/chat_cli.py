"""Minimal command-line interface for the Chat Adapter (Phase 6).

Run with: python3 scripts/chat_cli.py
Type a buyer request, then respond to the confirmation prompt with yes/no.
Type 'exit' or Ctrl+C to quit.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.catalog.seed_data import seed
from app.chat_adapter.adapter import ChatSession


def main() -> None:
    seed()
    session = ChatSession()
    print("NEXUS Chat — Northlight Outdoors. Type 'exit' to quit.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in ("exit", "quit"):
            break
        if not text:
            continue
        reply = session.handle_message(text)
        print(f"NEXUS: {reply}")
        if session.last_transaction_id:
            print(f"(transaction_id: {session.last_transaction_id} — "
                  f"view with: python3 scripts/view_audit_trail.py {session.last_transaction_id})")
        print()


if __name__ == "__main__":
    main()
