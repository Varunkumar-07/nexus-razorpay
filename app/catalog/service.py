"""Catalog query layer.

Each function takes typed, primitive parameters and returns JSON-serializable
structures (list[dict] or dict | None), so they can be wired up directly as
LLM tool-calls in Phase 2 without an adapter layer in between.
"""

from typing import Optional

from .db import get_connection
from .models import Product


def _row_to_product(row) -> Product:
    return Product(
        id=row["id"],
        name=row["name"],
        category=row["category"],
        price_paise=row["price_paise"],
        stock=row["stock"],
        spec=row["spec"],
    )


def search_by_category(category: str) -> list[dict]:
    """Return all products in the given category (case-insensitive exact match).

    Args:
        category: e.g. "tents", "sleeping_bags", "backpacks", "cooking_gear", "accessories"

    Returns:
        List of product dicts, sorted ascending by price. Empty list if none match.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM products WHERE LOWER(category) = LOWER(?) ORDER BY price_paise ASC",
            (category,),
        ).fetchall()
        return [_row_to_product(r).to_dict() for r in rows]
    finally:
        conn.close()


def filter_by_max_price(max_price_paise: int, category: Optional[str] = None) -> list[dict]:
    """Return products priced at or below max_price_paise, optionally scoped to a category.

    Args:
        max_price_paise: upper price bound, in paise (e.g. 300000 = Rs. 3000)
        category: optional category filter, exact match, case-insensitive

    Returns:
        List of product dicts, sorted ascending by price. Empty list if none match.
    """
    conn = get_connection()
    try:
        if category:
            rows = conn.execute(
                "SELECT * FROM products WHERE price_paise <= ? AND LOWER(category) = LOWER(?) "
                "ORDER BY price_paise ASC",
                (max_price_paise, category),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM products WHERE price_paise <= ? ORDER BY price_paise ASC",
                (max_price_paise,),
            ).fetchall()
        return [_row_to_product(r).to_dict() for r in rows]
    finally:
        conn.close()


def search_by_keyword(keyword: str) -> list[dict]:
    """Return products whose name or spec text contains the given keyword (case-insensitive).

    Args:
        keyword: free-text term, e.g. "winter", "2-person", "waterproof"

    Returns:
        List of product dicts, sorted ascending by price. Empty list if none match.
    """
    conn = get_connection()
    try:
        pattern = f"%{keyword}%"
        rows = conn.execute(
            "SELECT * FROM products WHERE name LIKE ? COLLATE NOCASE "
            "OR spec LIKE ? COLLATE NOCASE ORDER BY price_paise ASC",
            (pattern, pattern),
        ).fetchall()
        return [_row_to_product(r).to_dict() for r in rows]
    finally:
        conn.close()


def get_product_by_id(product_id: int) -> Optional[dict]:
    """Return a single product by its id.

    Args:
        product_id: the product's integer id

    Returns:
        Product dict, or None if no product with that id exists.
    """
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return _row_to_product(row).to_dict() if row else None
    finally:
        conn.close()
