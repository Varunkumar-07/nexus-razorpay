"""Agent API Adapter (Phase 7, Part A) — the machine-facing entry point.

A structured, documented HTTP API exposing the same core engine used by the
Chat Adapter (Phase 6): Catalog Service (Phase 1), the Gate (Phase 3), and
Razorpay order creation (Phase 5) — all under the shared Audit Log
(Phase 4). Every event this adapter generates is tagged source="agent".

This is deliberately NOT a chat endpoint — callers are other software
agents making structured calls, not humans typing natural language. The
recommendation logic here is a small deterministic "best fit under budget"
rule (not an LLM call): the calling agent is expected to supply its own
reasoning, the same way a real agent-to-agent commerce protocol would.

Run standalone:
    uvicorn app.agent_api.main:app --reload
Then browse http://127.0.0.1:8000/docs for the interactive OpenAPI docs,
or http://127.0.0.1:8000/ for the human Chat web UI (Phase 10 — a thin
HTTP wrapper + static frontend over the unmodified Phase 6 ChatSession,
mounted at the end of this file so it never shadows the API routes above).
"""

from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent_api.catalog_search import search_catalog
from app.agent_api.schemas import OrderRequest, OrderResponse, ProductOut, RecommendRequest, RecommendResponse
from app.audit.audit_log import log_event, new_transaction_id
from app.catalog.seed_data import seed
from app.gate.gate import check_gate
from app.metrics.routes import router as metrics_router
from app.razorpay_integration.orders import GateNotApprovedError, create_order
from app.web_chat.catalog_routes import router as catalog_page_router
from app.web_chat.pages import router as web_pages_router
from app.web_chat.routes import router as web_chat_router

SOURCE = "agent"

seed()  # ensure the catalog exists whenever this module is imported/run

app = FastAPI(
    title="NEXUS Agent API",
    description=(
        "Structured, machine-callable commerce endpoint for Northlight Outdoors "
        "(Razorpay AI Buildathon, Track 01). Exposes the same Catalog Service, "
        "Gate, and Razorpay integration used by the human Chat Adapter — every "
        "event here is tagged source='agent' in the shared Audit Log, and "
        "orders are governed by the exact same Gate rules (Rs.5,000 "
        "auto-approval bound, explicit confirmation, non-empty reasoning) as "
        "the human path. No shortcuts, no separate gate implementation."
    ),
    version="1.0.0",
)

# CORS for the separate React + Vite frontend (frontend/), which runs on
# its own dev server origin instead of being served by this FastAPI app.
# Additive only — no existing route logic is touched.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/catalog/search",
    response_model=List[ProductOut],
    summary="Search the Northlight Outdoors catalog",
    description=(
        "Read-only catalog search for machine callers. Combines category, "
        "max_price_paise, and keyword filters — any combination, all optional. "
        "Wraps Phase 1's catalog query functions directly. Logs one "
        "catalog_query audit event (source='agent') per call."
    ),
)
def catalog_search(
    category: Optional[str] = Query(None, description="Exact category, e.g. 'tents'."),
    max_price_paise: Optional[int] = Query(None, description="Upper price bound, in paise."),
    keyword: Optional[str] = Query(None, description="Free-text keyword match."),
) -> List[dict]:
    results = search_catalog(category=category, max_price_paise=max_price_paise, keyword=keyword)
    log_event(
        transaction_id=new_transaction_id(),
        source=SOURCE,
        event_type="catalog_query",
        details={
            "endpoint": "/catalog/search",
            "category": category,
            "max_price_paise": max_price_paise,
            "keyword": keyword,
            "result_count": len(results),
        },
    )
    return results


@app.post(
    "/recommend",
    response_model=RecommendResponse,
    summary="Get a structured recommendation for a buyer intent",
    description=(
        "Deterministic, structured recommendation for machine callers: given "
        "category / max_price_paise / keywords, selects the best-fit product "
        "under budget (the highest-priced match at or under the budget), or "
        "the cheapest match if no budget is given. Returns the same shape as "
        "the Chat Adapter's recommendation (Phase 2): transaction_id, "
        "no_match, primary, upsell, reasoning. Opens a new transaction thread "
        "in the Audit Log, source='agent'. Does not touch Razorpay or create "
        "any order."
    ),
)
def recommend_structured(payload: RecommendRequest) -> dict:
    transaction_id = new_transaction_id()

    candidates = search_catalog(
        category=payload.category,
        max_price_paise=payload.max_price_paise,
        keyword=payload.keywords,
    )
    log_event(
        transaction_id=transaction_id,
        source=SOURCE,
        event_type="catalog_query",
        details={
            "endpoint": "/recommend",
            "category": payload.category,
            "max_price_paise": payload.max_price_paise,
            "keywords": payload.keywords,
            "result_count": len(candidates),
        },
    )

    if not candidates:
        result = {
            "transaction_id": transaction_id,
            "no_match": True,
            "primary": None,
            "upsell": None,
            "reasoning": (
                f"No products matched category={payload.category!r}, "
                f"max_price_paise={payload.max_price_paise!r}, keywords={payload.keywords!r}."
            ),
        }
    elif payload.max_price_paise is not None:
        primary = max(candidates, key=lambda p: p["price_paise"])
        result = {
            "transaction_id": transaction_id,
            "no_match": False,
            "primary": primary,
            "upsell": None,
            "reasoning": (
                f"Selected {primary['name']} (Rs.{primary['price_paise'] / 100:.2f}) as the "
                f"best fit under the Rs.{payload.max_price_paise / 100:.2f} budget, out of "
                f"{len(candidates)} matching product(s)."
            ),
        }
    else:
        primary = min(candidates, key=lambda p: p["price_paise"])
        result = {
            "transaction_id": transaction_id,
            "no_match": False,
            "primary": primary,
            "upsell": None,
            "reasoning": (
                f"No budget given — selected the lowest-priced match, {primary['name']} "
                f"(Rs.{primary['price_paise'] / 100:.2f}), out of {len(candidates)} matching product(s)."
            ),
        }

    log_event(
        transaction_id=transaction_id,
        source=SOURCE,
        event_type="recommendation",
        details={
            "category": payload.category,
            "max_price_paise": payload.max_price_paise,
            "keywords": payload.keywords,
            "no_match": result["no_match"],
            "primary_product_id": result["primary"]["id"] if result["primary"] else None,
            "reasoning": result["reasoning"],
        },
    )

    return result


@app.post(
    "/order",
    response_model=OrderResponse,
    summary="Confirm and place an order",
    description=(
        "Runs the exact same Gate (Phase 3) used by the human Chat Adapter — "
        "amount bounded to Rs.5,000, explicit confirmed=true required, "
        "non-empty reasoning required — then, only if approved, creates a "
        "real Razorpay test-mode order (Phase 5) and fetches its payment "
        "status. If the Gate rejects, no Razorpay call is made and the "
        "rejection reason is returned. Every step is logged under "
        "transaction_id, source='agent'."
    ),
)
def place_order(payload: OrderRequest) -> dict:
    gate_result = check_gate(
        amount_paise=payload.amount_paise,
        confirmed=payload.confirmed,
        reasoning=payload.reasoning,
        transaction_id=payload.transaction_id,
        source=SOURCE,
    )

    if not gate_result["approved"]:
        return {
            "approved": False,
            "transaction_id": payload.transaction_id,
            "reason": gate_result["reason"],
            "order": None,
            "payment_status": None,
        }

    try:
        order_result = create_order(gate_result, transaction_id=payload.transaction_id, source=SOURCE)
    except GateNotApprovedError as exc:
        # Defensive only: gate_result["approved"] is already True on this path.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not order_result["success"]:
        return {
            "approved": True,
            "transaction_id": payload.transaction_id,
            "reason": order_result["error"],
            "order": None,
            "payment_status": None,
        }

    return {
        "approved": True,
        "transaction_id": payload.transaction_id,
        "reason": None,
        "order": order_result["order"],
        "payment_status": order_result["payment_status"],
    }


# --- Web Chat UI (Phase 10) -------------------------------------------------
# Additive only: wraps the existing, unmodified Phase 6 ChatSession over HTTP
# (see app/web_chat/routes.py) and serves its static frontend. catalog_all
# (GET /catalog/all) is a separate, read-only listing for the browsable
# product page (app/web_chat/catalog_routes.py) — reuses Phase 1's catalog
# functions unmodified, no chat/gate/order logic. The static mount is
# registered last, at "/", so it only ever catches requests that don't match
# an explicit route above (e.g. "/", "/style.css", "/app.js", "/products.js")
# — it never shadows /catalog/search, /catalog/all, /recommend, /order,
# /chat/*, /products, or /docs.
app.include_router(web_chat_router)
app.include_router(catalog_page_router)
app.include_router(web_pages_router)
app.include_router(metrics_router)

_WEB_CHAT_STATIC_DIR = Path(__file__).resolve().parent.parent / "web_chat" / "static"
app.mount("/", StaticFiles(directory=str(_WEB_CHAT_STATIC_DIR), html=True), name="web_chat_ui")
