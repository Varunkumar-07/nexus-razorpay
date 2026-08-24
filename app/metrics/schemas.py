"""Pydantic response models for GET /metrics/summary."""

from typing import Dict

from pydantic import BaseModel, Field


class SourceBreakdown(BaseModel):
    order_count: int
    revenue_rupees: float = Field(..., description="Total revenue from this source, in rupees.")


class GateRejectionBreakdown(BaseModel):
    over_bound: int = Field(..., description="Gate checks rejected for exceeding the Rs.5,000 bound.")
    declined: int = Field(..., description="Buyer explicitly said no.")
    unclear: int = Field(..., description="Buyer's reply at confirmation was ambiguous.")


class MetricsSummary(BaseModel):
    total_orders: int
    total_revenue_rupees: float
    average_order_value_rupees: float
    upsell_offer_rate: float = Field(..., description="Fraction (0-1) of matched recommendations that included an upsell.")
    upsell_acceptance_rate: float = Field(
        ...,
        description=(
            "Fraction (0-1) of offered upsells the buyer accepted (chose 'yes' for both "
            "over 'primary only'), among buyers who made an explicit choice either way."
        ),
    )
    gate_rejection_rate: float = Field(
        ..., description="Fraction (0-1) of confirmation attempts that did not result in an order."
    )
    gate_rejection_breakdown: GateRejectionBreakdown
    by_source: Dict[str, SourceBreakdown]
