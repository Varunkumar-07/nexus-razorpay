"""Metrics Service.

Read-only analytics computed entirely from the existing Audit Log — no new
tables, no schema changes. Every number here is an aggregation over rows
Phases 2-7 already write (recommendation, gate_check, order_created,
order_declined, confirmation_unclear events), read via
app.audit.audit_log.get_events_by_type().

Two new event_type values (order_declined, confirmation_unclear) were added
to ChatSession's confirmation flow to make this computable at all: without
them, a buyer's explicit "no" and an unclear/ambiguous reply are otherwise
indistinguishable in the trail — both simply leave a recommendation event
with no follow-up. That's the only change to any existing pipeline code;
this module itself is pure aggregation, read-only, and has no side effects.
"""

from app.audit.audit_log import get_events_by_type
from app.catalog.service import get_product_by_id

SOURCES = ("chat", "agent")


class MetricsService:
    """Aggregates the Audit Log into a single metrics summary."""

    @staticmethod
    def get_summary() -> dict:
        order_events = get_events_by_type("order_created")
        recommendation_events = get_events_by_type("recommendation")
        gate_check_events = get_events_by_type("gate_check")
        declined_events = get_events_by_type("order_declined")
        unclear_events = get_events_by_type("confirmation_unclear")

        total_orders = len(order_events)
        total_revenue_paise = sum(_order_amount(e) for e in order_events)
        average_order_value_paise = (total_revenue_paise / total_orders) if total_orders else 0

        by_source = {
            src: _source_breakdown(order_events, src) for src in SOURCES
        }

        matched_recommendations = [e for e in recommendation_events if not e["details"].get("no_match")]
        total_matched = len(matched_recommendations)
        with_upsell = [
            e for e in matched_recommendations if e["details"].get("upsell_product_id") is not None
        ]
        upsell_offer_rate = (len(with_upsell) / total_matched) if total_matched else 0.0

        accepted_full, considered = _upsell_decision_counts(with_upsell, gate_check_events)
        upsell_acceptance_rate = (accepted_full / considered) if considered else 0.0

        over_bound_count = sum(1 for g in gate_check_events if not g["details"]["approved"])
        declined_count = len(declined_events)
        unclear_count = len(unclear_events)
        total_attempts = len(gate_check_events) + declined_count + unclear_count
        total_rejected = over_bound_count + declined_count + unclear_count
        gate_rejection_rate = (total_rejected / total_attempts) if total_attempts else 0.0

        return {
            "total_orders": total_orders,
            "total_revenue_paise": total_revenue_paise,
            "average_order_value_paise": average_order_value_paise,
            "upsell_offer_rate": upsell_offer_rate,
            "upsell_acceptance_rate": upsell_acceptance_rate,
            "gate_rejection_rate": gate_rejection_rate,
            "gate_rejection_breakdown": {
                "over_bound": over_bound_count,
                "declined": declined_count,
                "unclear": unclear_count,
            },
            "by_source": by_source,
        }


def _order_amount(order_event: dict) -> int:
    return order_event["details"]["order"]["amount"]


def _source_breakdown(order_events: list[dict], source: str) -> dict:
    src_orders = [e for e in order_events if e["source"] == source]
    return {
        "order_count": len(src_orders),
        "revenue_paise": sum(_order_amount(e) for e in src_orders),
    }


def _upsell_decision_counts(with_upsell_recommendations: list[dict], gate_check_events: list[dict]) -> tuple:
    """For each recommendation that offered an upsell, determine whether the
    buyer's eventual Gate decision (if any) was for the full bundle or the
    primary item only, by comparing the actual gated amount — which reflects
    the buyer's choice regardless of whether the Gate approved it — against
    the two amounts computable from the recommendation plus current catalog
    prices.

    Returns:
        (accepted_full_bundle_count, considered_count). considered_count
        only includes transactions that reached a Gate check at all — i.e.
        the buyer made an explicit yes/primary-only decision, not a decline,
        not an unclear reply, and not an abandoned conversation.
    """
    gate_by_transaction: dict = {}
    for g in gate_check_events:
        gate_by_transaction.setdefault(g["transaction_id"], []).append(g)

    accepted_full = 0
    considered = 0

    for rec in with_upsell_recommendations:
        gate_events_for_tx = gate_by_transaction.get(rec["transaction_id"])
        if not gate_events_for_tx:
            continue

        primary = get_product_by_id(rec["details"]["primary_product_id"])
        upsell = get_product_by_id(rec["details"]["upsell_product_id"])
        if not primary or not upsell:
            continue

        quantity = rec["details"].get("quantity", 1)
        primary_only_amount = primary["price_paise"] * quantity
        full_bundle_amount = primary_only_amount + upsell["price_paise"]

        # A transaction only ever reaches the Gate once in the current
        # ChatSession/Agent API flows — a Gate decision (approved or
        # rejected) always ends that conversation, never retries within
        # the same transaction_id — so the first gate_check is the decision.
        gated_amount = gate_events_for_tx[0]["details"]["amount_paise"]

        if gated_amount == full_bundle_amount:
            considered += 1
            accepted_full += 1
        elif gated_amount == primary_only_amount:
            considered += 1
        # else: doesn't match either computed value (e.g. catalog price
        # changed since) — skip rather than guess.

    return accepted_full, considered
