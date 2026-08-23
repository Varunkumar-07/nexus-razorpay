"""Phase 1 smoke test — run sample queries against the seeded catalog and
print results, to visually confirm the Catalog Service works.

Run with: python3 scripts/test_catalog.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.catalog.seed_data import seed
from app.catalog.service import (
    filter_by_max_price,
    get_product_by_id,
    search_by_category,
    search_by_keyword,
)


def print_results(label: str, results) -> None:
    print(f"\n=== {label} ===")
    if results is None:
        print("  (none found)")
        return
    if isinstance(results, list):
        if not results:
            print("  (no matches)")
        for p in results:
            print(
                f"  [{p['id']}] {p['name']} — Rs.{p['price_paise'] / 100:.2f} "
                f"— stock:{p['stock']} — {p['spec']}"
            )
    else:
        print(
            f"  [{results['id']}] {results['name']} — Rs.{results['price_paise'] / 100:.2f} "
            f"— stock:{results['stock']} — {results['spec']}"
        )


def main() -> None:
    seed()

    print_results("search_by_category('tents')", search_by_category("tents"))
    print_results(
        "filter_by_max_price(300000) — everything under Rs.3000",
        filter_by_max_price(300000),
    )
    print_results(
        "filter_by_max_price(500000, category='tents') — tents under Rs.5000",
        filter_by_max_price(500000, category="tents"),
    )
    print_results("search_by_keyword('winter')", search_by_keyword("winter"))
    print_results("search_by_keyword('2-person')", search_by_keyword("2-person"))
    print_results("get_product_by_id(1)", get_product_by_id(1))
    print_results("get_product_by_id(999) — should be None", get_product_by_id(999))


if __name__ == "__main__":
    main()
