"""Audit Log (Phase 4).

One row per significant pipeline event: catalog queries, recommendations,
gate decisions, and (from Phase 5 onward) order creation/failure. Every
entry belongs to a transaction thread — a single buyer request working its
way through the pipeline — so the full story of one transaction can be
retrieved and displayed in chronological order.

Shares the same SQLite database as the Catalog Service (app/catalog/db.py).
"""

import json
import uuid
from datetime import datetime, timezone

from app.catalog.db import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details TEXT NOT NULL
);
"""


def init_audit_log() -> None:
    conn = get_connection()
    try:
        conn.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def new_transaction_id() -> str:
    """Generate a new id to link related events into one transaction thread."""
    return uuid.uuid4().hex


def log_event(transaction_id: str, source: str, event_type: str, details: dict) -> int:
    """Write one audit log entry.

    Args:
        transaction_id: id linking this event to others in the same
            request -> recommendation -> gate-check thread. See new_transaction_id().
        source: "chat" or "agent" — which entry adapter this event belongs to.
            Use "unspecified" for standalone/test calls made before an adapter
            (Phase 6/7) sets this explicitly.
        event_type: e.g. "catalog_query", "recommendation", "gate_check",
            "order_created", "order_failed".
        details: structured, JSON-serializable payload for this event.

    Returns:
        The new row's id.
    """
    init_audit_log()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO audit_log (timestamp, transaction_id, source, event_type, details) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                transaction_id,
                source,
                event_type,
                json.dumps(details),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_events_by_type(event_type: str) -> list[dict]:
    """Retrieve every event of one type, across all transactions, in
    chronological order.

    Read-only, cross-transaction — the counterpart to get_transaction_trail()
    (which is scoped to one transaction_id). Used by MetricsService
    (app/metrics/) to aggregate over the existing Audit Log without any
    schema changes.

    Args:
        event_type: e.g. "recommendation", "gate_check", "order_created",
            "order_declined", "confirmation_unclear".

    Returns:
        List of event dicts: {id, timestamp, transaction_id, source,
        event_type, details}, ordered oldest first.
    """
    init_audit_log()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE event_type = ? ORDER BY id ASC",
            (event_type,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "transaction_id": row["transaction_id"],
                "source": row["source"],
                "event_type": row["event_type"],
                "details": json.loads(row["details"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_transaction_trail(transaction_id: str) -> list[dict]:
    """Retrieve the full audit trail for one transaction, in chronological order.

    Args:
        transaction_id: the transaction id to look up.

    Returns:
        List of event dicts: {id, timestamp, transaction_id, source, event_type,
        details}, ordered oldest first. Empty list if the transaction id is unknown.
    """
    init_audit_log()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE transaction_id = ? ORDER BY id ASC",
            (transaction_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "transaction_id": row["transaction_id"],
                "source": row["source"],
                "event_type": row["event_type"],
                "details": json.loads(row["details"]),
            }
            for row in rows
        ]
    finally:
        conn.close()
