"""Standalone static page routes for the web frontend.

Gives the browsable product catalog a clean "/products" URL (instead of
colliding with the "/catalog/*" API namespace, or needing a ".html"
suffix). Registered as explicit routes ahead of the catch-all static
mount in app/agent_api/main.py, so this always wins for an exact
"/products" request.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["pages"])

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@router.get("/products", include_in_schema=False, summary="Browsable product catalog page")
def products_page() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "products.html"))
