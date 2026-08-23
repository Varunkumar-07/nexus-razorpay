"""Pydantic request/response models for the Agent API Adapter (Phase 7).

These models are what generate the OpenAPI schema at /docs — the
"documented endpoint" the project brief calls for.
"""

from typing import Optional

from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    id: int
    name: str
    category: str
    price_paise: int = Field(..., description="Price in paise (INR * 100).")
    stock: int
    spec: str


class RecommendRequest(BaseModel):
    category: Optional[str] = Field(
        None, description="Exact catalog category, e.g. 'tents', 'sleeping_bags'."
    )
    max_price_paise: Optional[int] = Field(
        None, description="Upper price bound in paise, e.g. 500000 = Rs. 5000."
    )
    keywords: Optional[str] = Field(
        None,
        description="Optional single free-text keyword to match against product name/spec (e.g. 'winter').",
    )


class RecommendResponse(BaseModel):
    transaction_id: str = Field(..., description="Links this recommendation to its later Gate check / order.")
    no_match: bool
    primary: Optional[ProductOut] = None
    upsell: Optional[ProductOut] = None
    reasoning: str


class OrderRequest(BaseModel):
    transaction_id: str = Field(..., description="transaction_id returned by POST /recommend.")
    amount_paise: int = Field(
        ..., description="Total order amount in paise; must match the recommended product's price."
    )
    confirmed: bool = Field(
        ..., description="Explicit confirmation flag. Must be true — the Gate rejects otherwise."
    )
    reasoning: str = Field(
        ..., description="Non-empty reasoning behind this order. Required by the Gate."
    )


class OrderResponse(BaseModel):
    approved: bool = Field(..., description="Whether the Gate approved this order.")
    transaction_id: str
    reason: Optional[str] = Field(
        None, description="Set when approved is false, or when order creation itself failed."
    )
    order: Optional[dict] = Field(None, description="Raw Razorpay order object, if created.")
    payment_status: Optional[dict] = Field(None, description="Result of the Payments API status fetch.")
