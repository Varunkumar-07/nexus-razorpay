"""In-memory recommendation store for the Agent API Adapter (Phase 7).

Binds a POST /recommend response's selected product/amount to its
transaction_id, so POST /order can look up and charge the *actual*
recommended amount server-side instead of trusting whatever amount_paise
a caller sends in the /order request body. This gives the Agent API the
same "the buyer/agent can't just declare their own total" posture the
Chat Adapter already has by construction (it computes amount_paise from
catalog data directly, never from client input).

In-memory dict is fine for this build — same tradeoff as
app.web_chat.sessions: entries live for the lifetime of the server
process, matching the demo/single-process deployment.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class RecommendationRecord:
    product_id: int
    amount_paise: int


_RECOMMENDATIONS: Dict[str, RecommendationRecord] = {}


def store_recommendation(transaction_id: str, product_id: int, amount_paise: int) -> None:
    """Record the product/amount POST /recommend selected for transaction_id."""
    _RECOMMENDATIONS[transaction_id] = RecommendationRecord(product_id=product_id, amount_paise=amount_paise)


def get_recommendation(transaction_id: str) -> Optional[RecommendationRecord]:
    """Look up a stored recommendation by transaction_id, or None if none exists."""
    return _RECOMMENDATIONS.get(transaction_id)
