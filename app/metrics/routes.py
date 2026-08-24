"""HTTP route for the Metrics module.

Read-only — GET /metrics/summary just calls MetricsService.get_summary()
and converts paise to rupees for presentation. No side effects, no writes.
"""

from fastapi import APIRouter

from app.metrics.schemas import MetricsSummary
from app.metrics.service import SOURCES, MetricsService

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get(
    "/summary",
    response_model=MetricsSummary,
    summary="Business metrics computed from the Audit Log",
    description=(
        "Read-only analytics over the existing Audit Log — no separate metrics "
        "store, every number is derived live from the same events Phases 2-7 "
        "already write (recommendation, gate_check, order_created, "
        "order_declined, confirmation_unclear). Covers total orders and "
        "revenue, upsell offer/acceptance rates, the Gate rejection rate with "
        "a breakdown by cause (over-bound / declined / unclear), a chat-vs-"
        "agent source breakdown, and average order value."
    ),
)
def metrics_summary() -> dict:
    summary = MetricsService.get_summary()

    return {
        "total_orders": summary["total_orders"],
        "total_revenue_rupees": summary["total_revenue_paise"] / 100,
        "average_order_value_rupees": summary["average_order_value_paise"] / 100,
        "upsell_offer_rate": summary["upsell_offer_rate"],
        "upsell_acceptance_rate": summary["upsell_acceptance_rate"],
        "gate_rejection_rate": summary["gate_rejection_rate"],
        "gate_rejection_breakdown": summary["gate_rejection_breakdown"],
        "by_source": {
            src: {
                "order_count": summary["by_source"][src]["order_count"],
                "revenue_rupees": summary["by_source"][src]["revenue_paise"] / 100,
            }
            for src in SOURCES
        },
    }
