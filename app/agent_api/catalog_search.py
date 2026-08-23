"""Shared catalog-search combinator for the Agent API Adapter (Phase 7).

Wraps the four Phase 1 catalog functions directly — no product-query logic
is reimplemented here, results are only combined and post-filtered.
"""

from typing import List, Optional

from app.catalog.service import filter_by_max_price, search_by_category, search_by_keyword

# Effectively "no price limit" — used so filter_by_max_price can stand in for
# an unfiltered listing when neither category nor keyword narrows the search.
_ALL_PRODUCTS_CEILING_PAISE = 10**12


def search_catalog(
    category: Optional[str] = None,
    max_price_paise: Optional[int] = None,
    keyword: Optional[str] = None,
) -> List[dict]:
    """Combine the Phase 1 catalog query functions into one flexible search.

    Args:
        category: optional exact category filter.
        max_price_paise: optional upper price bound, in paise.
        keyword: optional free-text keyword (name/spec match).

    Returns:
        List of matching product dicts, sorted ascending by price.
    """
    if keyword:
        results = search_by_keyword(keyword)
    elif category:
        results = search_by_category(category)
    else:
        results = filter_by_max_price(
            max_price_paise if max_price_paise is not None else _ALL_PRODUCTS_CEILING_PAISE
        )

    if category and keyword:
        results = [p for p in results if p["category"].lower() == category.lower()]
    if max_price_paise is not None and (keyword or category):
        results = [p for p in results if p["price_paise"] <= max_price_paise]

    return sorted(results, key=lambda p: p["price_paise"])
