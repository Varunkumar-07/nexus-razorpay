"""LLM tool schemas + dispatch table for the Catalog Service (Phase 2).

Wraps the four Phase 1 catalog functions as OpenAI-style function-calling
schemas (Groq's tool-calling API uses the same shape), plus a dispatch table
that routes a tool call's name/arguments back to the real Python function.
"""

from app.catalog.service import (
    filter_by_max_price,
    get_product_by_id,
    search_by_category,
    search_by_keyword,
)

CATALOG_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_by_category",
            "description": (
                "Search the Northlight Outdoors catalog for all products in a given "
                "category. Categories: sleeping_bags, tents, backpacks, cooking_gear, "
                "accessories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Exact category name, e.g. 'tents' or 'sleeping_bags'.",
                    }
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "filter_by_max_price",
            "description": (
                "Find products priced at or below a budget, in paise (INR * 100), "
                "optionally scoped to one category."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_price_paise": {
                        "type": "integer",
                        "description": "Upper price bound in paise, e.g. 300000 = Rs. 3000.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter.",
                    },
                },
                "required": ["max_price_paise"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_keyword",
            "description": (
                "Free-text search over product name and spec text, e.g. 'winter', "
                "'2-person', 'waterproof'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search term."}
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_by_id",
            "description": "Fetch a single product's full details by its integer id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "Product id."}
                },
                "required": ["product_id"],
            },
        },
    },
]

TOOL_DISPATCH = {
    "search_by_category": lambda args: search_by_category(args["category"]),
    "filter_by_max_price": lambda args: filter_by_max_price(
        args["max_price_paise"], args.get("category")
    ),
    "search_by_keyword": lambda args: search_by_keyword(args["keyword"]),
    "get_product_by_id": lambda args: get_product_by_id(args["product_id"]),
}

FINAL_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "propose_recommendation",
        "description": (
            "Submit the final recommendation. Call this exactly once, after you've "
            "used the catalog tools to find real matching products. Never invent "
            "product ids that didn't come back from a catalog tool call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "no_match": {
                    "type": "boolean",
                    "description": (
                        "True if no product reasonably satisfies the request "
                        "(e.g. budget too low for anything in stock)."
                    ),
                },
                "primary_product_id": {
                    "type": ["integer", "null"],
                    "description": "Id of the best-matching product, or null if no_match is true.",
                },
                "quantity": {
                    "type": "integer",
                    "description": (
                        "How many units of the PRIMARY product the buyer wants. Parse this from "
                        "explicit quantity language in the request (e.g. 'x2', '2x', 'two of', "
                        "'a couple of'). Defaults to 1 if the buyer didn't state a quantity. This "
                        "applies ONLY to the primary product — the upsell is always a single unit, "
                        "regardless of the primary's quantity."
                    ),
                },
                "upsell_product_id": {
                    "type": ["integer", "null"],
                    "description": (
                        "Id of one legitimate complementary product to upsell/cross-sell, "
                        "or null if none fits. This is always a single extra unit — it must "
                        "never be used as a substitute for, or confused with, the quantity of "
                        "the primary product the buyer explicitly asked for."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "Short natural-language explanation of the recommendation "
                        "(or of why there's no match)."
                    ),
                },
            },
            "required": ["no_match", "primary_product_id", "quantity", "upsell_product_id", "reasoning"],
        },
    },
}
