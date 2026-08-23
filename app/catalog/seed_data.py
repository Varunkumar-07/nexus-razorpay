"""Seed data for the Northlight Outdoors catalog (Phase 1).

15 products across 5 categories. Prices are in paise (Razorpay subunit
format: price_paise = INR * 100).
"""

from .db import get_connection, init_db

PRODUCTS = [
    # sleeping_bags
    {
        "id": 1,
        "name": "Arctic Pro Sleeping Bag",
        "category": "sleeping_bags",
        "price_paise": 279900,
        "stock": 12,
        "spec": "Winter-rated to -15C, mummy shape, synthetic fill, fits up to 6ft2.",
    },
    {
        "id": 2,
        "name": "Summit Ultralight Sleeping Bag",
        "category": "sleeping_bags",
        "price_paise": 349900,
        "stock": 8,
        "spec": "3-season rated, synthetic fill, packs to 20x35cm, 1.1kg.",
    },
    {
        "id": 3,
        "name": "TrailLite 3-Season Sleeping Bag",
        "category": "sleeping_bags",
        "price_paise": 199900,
        "stock": 20,
        "spec": "3-season rectangular bag, budget-friendly, machine washable.",
    },
    {
        "id": 4,
        "name": "Glacier Extreme Sleeping Bag",
        "category": "sleeping_bags",
        "price_paise": 499900,
        "stock": 5,
        "spec": "Winter-rated to -25C, premium down fill, expedition grade.",
    },
    # tents
    {
        "id": 5,
        "name": "StormShield 2-Person Tent",
        "category": "tents",
        "price_paise": 459900,
        "stock": 10,
        "spec": "2-person, 3-season, waterproof rainfly, freestanding design.",
    },
    {
        "id": 6,
        "name": "Basecamp 4-Person Tent",
        "category": "tents",
        "price_paise": 699900,
        "stock": 6,
        "spec": "4-person family tent, 3-season, two-room layout, easy setup.",
    },
    {
        "id": 7,
        "name": "SoloPeak 1-Person Tent",
        "category": "tents",
        "price_paise": 299900,
        "stock": 15,
        "spec": "1-person ultralight tent, 3-season, 1.4kg, solo backpacking.",
    },
    {
        "id": 8,
        "name": "AlpineGuard Winter Tent",
        "category": "tents",
        "price_paise": 899900,
        "stock": 4,
        "spec": "4-season winter-rated tent, reinforced poles, snow-load capable.",
    },
    # backpacks
    {
        "id": 9,
        "name": "TrailBlazer 50L Backpack",
        "category": "backpacks",
        "price_paise": 329900,
        "stock": 14,
        "spec": "50L capacity, multi-day trekking, adjustable torso, rain cover included.",
    },
    {
        "id": 10,
        "name": "DayHiker 25L Backpack",
        "category": "backpacks",
        "price_paise": 149900,
        "stock": 25,
        "spec": "25L daypack, lightweight, hydration bladder compatible.",
    },
    {
        "id": 11,
        "name": "ExpeditionMax 65L Backpack",
        "category": "backpacks",
        "price_paise": 549900,
        "stock": 7,
        "spec": "65L expedition pack, internal frame, heavy-load multi-week trips.",
    },
    {
        "id": 12,
        "name": "Compact 20L Backpack",
        "category": "backpacks",
        "price_paise": 99900,
        "stock": 30,
        "spec": "20L compact daypack, lightweight, ideal for short hikes.",
    },
    # cooking_gear
    {
        "id": 13,
        "name": "TrailChef Portable Stove",
        "category": "cooking_gear",
        "price_paise": 179900,
        "stock": 18,
        "spec": "Compact butane camp stove, piezo ignition, 350g.",
    },
    {
        "id": 14,
        "name": "Camp Cook Set (4-piece)",
        "category": "cooking_gear",
        "price_paise": 129900,
        "stock": 22,
        "spec": "Lightweight aluminum pots and pans, nesting design, serves 2.",
    },
    # accessories
    {
        "id": 15,
        "name": "CloudRest Sleeping Pad",
        "category": "accessories",
        "price_paise": 49900,
        "stock": 40,
        "spec": "Insulated self-inflating sleeping mat, 2-season, compatible with most sleeping bags.",
    },
]


def seed() -> None:
    """Create the schema (if needed) and insert PRODUCTS if the table is empty."""
    init_db()
    conn = get_connection()
    try:
        existing = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if existing > 0:
            return
        conn.executemany(
            "INSERT INTO products (id, name, category, price_paise, stock, spec) "
            "VALUES (:id, :name, :category, :price_paise, :stock, :spec)",
            PRODUCTS,
        )
        conn.commit()
    finally:
        conn.close()
