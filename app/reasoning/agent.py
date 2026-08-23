"""Agent Reasoning Core (Phase 2).

Given a natural-language buyer request, queries the Catalog Service via LLM
tool-calling (Groq) and returns a structured recommendation: primary product,
optional upsell, and a short explanation.

This module deliberately does NOT touch Razorpay or create any order — that
happens in Phase 5, after the Gate (Phase 3) and Audit Log (Phase 4) exist.
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv
from groq import Groq

from app.audit.audit_log import log_event, new_transaction_id
from app.catalog.service import get_product_by_id
from app.reasoning.tools import CATALOG_TOOL_SCHEMAS, FINAL_TOOL_SCHEMA, TOOL_DISPATCH

load_dotenv()

MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = """You are the shopping assistant for Northlight Outdoors, a camping gear merchant.

You have catalog tools to search real products. Use them to find products that
actually match the buyer's request and budget. Never invent a product or a
product id — only recommend products that came back from a tool call.

Your job:
1. Find the best-matching primary product for the buyer's request.
2. Check the request for an explicit quantity of the primary product (e.g.
   "x2", "2x", "two of", "a couple of"). If one is stated, set quantity to
   that number; otherwise quantity is 1. Never drop or ignore an explicit
   quantity — it directly changes the order total.
3. Identify at most one legitimate upsell or cross-sell: a genuinely
   complementary product (e.g. a sleeping pad for a sleeping bag, a stove for
   a cook set), not a random unrelated item. If nothing complementary exists
   in the catalog, leave the upsell out. The upsell is always exactly one
   extra unit — it is never a substitute for, and never affected by, the
   primary product's quantity. Do not let an upsell distract you from
   getting the primary product and its quantity right.
4. If nothing in the catalog reasonably satisfies the request (e.g. the
   budget is too low for anything in stock, or the category doesn't exist),
   do not force a bad recommendation — set no_match to true and explain why.

When you're done reasoning, call propose_recommendation exactly once with your
final answer, including the correct quantity for the primary product."""


class ReasoningError(RuntimeError):
    """Raised when the reasoning core fails to produce a usable recommendation."""


def _run_tool_call(tool_call, transaction_id: str, source: str) -> dict:
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments or "{}")
    fn = TOOL_DISPATCH.get(name)
    result = {"error": f"Unknown tool: {name}"} if fn is None else fn(args)

    log_event(
        transaction_id=transaction_id,
        source=source,
        event_type="catalog_query",
        details={"tool": name, "args": args, "result": result},
    )
    return result


def recommend(
    request: str,
    max_tool_iterations: int = 6,
    transaction_id: Optional[str] = None,
    source: str = "unspecified",
) -> dict:
    """Produce a structured recommendation for a natural-language buyer request.

    Args:
        request: free-text buyer request, e.g.
            "I need a good sleeping bag for winter camping, budget around Rs.3000."
        max_tool_iterations: safety cap on catalog tool round-trips before giving up.
        transaction_id: id linking this call's audit log events to a shared
            transaction thread (e.g. with a later Gate check). Generated
            automatically if not provided.
        source: "chat" or "agent" — which entry adapter triggered this call.
            Defaults to "unspecified" for standalone/test use before Phase 6/7
            adapters exist.

    Returns:
        {
            "transaction_id": str,
            "no_match": bool,
            "primary": dict | None,   # full product dict
            "quantity": int,          # units of primary, parsed from the request; always 1 for the upsell
            "upsell": dict | None,    # full product dict, always exactly one unit
            "reasoning": str,
        }

    Raises:
        ReasoningError: if GROQ_API_KEY is missing, the API call fails, or the
            model never converges on a final recommendation within
            max_tool_iterations.
    """
    if transaction_id is None:
        transaction_id = new_transaction_id()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ReasoningError("GROQ_API_KEY is not set in the environment.")

    client = Groq(api_key=api_key)
    tools = CATALOG_TOOL_SCHEMAS + [FINAL_TOOL_SCHEMA]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request},
    ]

    try:
        for _ in range(max_tool_iterations):
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            message = response.choices[0].message

            if not message.tool_calls:
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": "Please call propose_recommendation with your final answer.",
                    }
                )
                continue

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            for tool_call in message.tool_calls:
                if tool_call.function.name == "propose_recommendation":
                    args = json.loads(tool_call.function.arguments or "{}")
                    return _build_result(args, transaction_id, source, request)

                result = _run_tool_call(tool_call, transaction_id, source)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    }
                )
    except ReasoningError:
        raise
    except Exception as exc:  # Groq API/network errors
        raise ReasoningError(f"Groq API call failed: {exc}") from exc

    raise ReasoningError(
        f"Agent did not converge on a recommendation within {max_tool_iterations} tool iterations."
    )


def _parse_quantity(raw_quantity) -> int:
    """Defensively coerce the model's quantity argument to a positive int.

    Falls back to 1 (never 0 or negative, never non-numeric) so a malformed
    or missing quantity can't silently zero out an order or crash amount
    calculations downstream.
    """
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        return 1
    return quantity if quantity >= 1 else 1


def _build_result(args: dict, transaction_id: str, source: str, request: str) -> dict:
    no_match = bool(args.get("no_match", False))
    primary_id = args.get("primary_product_id")
    upsell_id = args.get("upsell_product_id")

    primary = get_product_by_id(primary_id) if primary_id else None
    upsell = get_product_by_id(upsell_id) if upsell_id else None
    reasoning = args.get("reasoning", "")
    no_match = no_match or primary is None
    # Quantity only means something when there's an actual primary product.
    quantity = _parse_quantity(args.get("quantity", 1)) if primary else 1

    log_event(
        transaction_id=transaction_id,
        source=source,
        event_type="recommendation",
        details={
            "request": request,
            "no_match": no_match,
            "primary_product_id": primary["id"] if primary else None,
            "quantity": quantity,
            "upsell_product_id": upsell["id"] if upsell else None,
            "reasoning": reasoning,
        },
    )

    return {
        "transaction_id": transaction_id,
        "no_match": no_match,
        "primary": primary,
        "quantity": quantity,
        "upsell": upsell,
        "reasoning": reasoning,
    }
