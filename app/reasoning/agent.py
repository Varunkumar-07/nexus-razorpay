"""Agent Reasoning Core (Phase 2).

Given a natural-language buyer request, queries the Catalog Service via LLM
tool-calling (Groq) and returns a structured recommendation: primary product,
optional upsell, and a short explanation.

This module deliberately does NOT touch Razorpay or create any order — that
happens in Phase 5, after the Gate (Phase 3) and Audit Log (Phase 4) exist.
"""

import json
import os

from dotenv import load_dotenv
from groq import Groq

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
2. Identify at most one legitimate upsell or cross-sell: a genuinely
   complementary product (e.g. a sleeping pad for a sleeping bag, a stove for
   a cook set), not a random unrelated item. If nothing complementary exists
   in the catalog, leave the upsell out.
3. If nothing in the catalog reasonably satisfies the request (e.g. the
   budget is too low for anything in stock, or the category doesn't exist),
   do not force a bad recommendation — set no_match to true and explain why.

When you're done reasoning, call propose_recommendation exactly once with your
final answer."""


class ReasoningError(RuntimeError):
    """Raised when the reasoning core fails to produce a usable recommendation."""


def _run_tool_call(tool_call) -> dict:
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments or "{}")
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    return fn(args)


def recommend(request: str, max_tool_iterations: int = 6) -> dict:
    """Produce a structured recommendation for a natural-language buyer request.

    Args:
        request: free-text buyer request, e.g.
            "I need a good sleeping bag for winter camping, budget around Rs.3000."
        max_tool_iterations: safety cap on catalog tool round-trips before giving up.

    Returns:
        {
            "no_match": bool,
            "primary": dict | None,   # full product dict
            "upsell": dict | None,    # full product dict
            "reasoning": str,
        }

    Raises:
        ReasoningError: if GROQ_API_KEY is missing, the API call fails, or the
            model never converges on a final recommendation within
            max_tool_iterations.
    """
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
                    return _build_result(args)

                result = _run_tool_call(tool_call)
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


def _build_result(args: dict) -> dict:
    no_match = bool(args.get("no_match", False))
    primary_id = args.get("primary_product_id")
    upsell_id = args.get("upsell_product_id")

    primary = get_product_by_id(primary_id) if primary_id else None
    upsell = get_product_by_id(upsell_id) if upsell_id else None

    return {
        "no_match": no_match or primary is None,
        "primary": primary,
        "upsell": upsell,
        "reasoning": args.get("reasoning", ""),
    }
