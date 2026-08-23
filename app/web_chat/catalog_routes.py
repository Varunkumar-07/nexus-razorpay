"""Read-only catalog listing endpoint for the web frontend's browsable
product page.

Purely additive: reuses Phase 1's filter_by_max_price() unmodified (the
same "no upper bound" trick already used in
app/agent_api/catalog_search.py) to fetch every product, then groups the
results by category in plain Python. No chat, gate, or order logic here.
"""

from typing import Dict, List

from fastapi import APIRouter

from app.agent_api.schemas import ProductOut
from app.catalog.service import filter_by_max_price

router = APIRouter(prefix="/catalog", tags=["catalog-page"])

# Effectively "no price limit" — see app/agent_api/catalog_search.py for the
# same pattern.
_ALL_PRODUCTS_CEILING_PAISE = 10**12


@router.get(
    "/all",
    response_model=Dict[str, List[ProductOut]],
    summary="List every product, grouped by category",
    description=(
        "Read-only catalog listing for the browsable /products page. "
        "Reuses Phase 1's filter_by_max_price() with no upper bound to fetch "
        "every product, then groups them by category."
    ),
)
def catalog_all() -> Dict[str, List[dict]]:
    products = filter_by_max_price(_ALL_PRODUCTS_CEILING_PAISE)
    grouped: Dict[str, List[dict]] = {}
    for product in products:
        grouped.setdefault(product["category"], []).append(product)
    return grouped
