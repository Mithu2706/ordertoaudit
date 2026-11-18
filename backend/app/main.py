"""FastAPI application entry point: `uvicorn app.main:app --reload`."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import auth, billing, dashboard, inventory, items, parties, production, purchases, reference, reports, sales, users
from app.core.config import check_production_settings, get_settings
from app.core.errors import NotFoundError, register_exception_handlers

API_PREFIX = "/api"


def create_app() -> FastAPI:
    settings = get_settings()
    check_production_settings(settings)
    app = FastAPI(
        title="Order-to-Audit System",
        version="1.0.0",
        description="Sales → Verification → GST Invoice → Dispatch → Inventory → Production → Costing → Audit",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
        swagger_ui_oauth2_redirect_url=f"{API_PREFIX}/docs/oauth2-redirect",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # bearer tokens, no cookies
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_exception_handlers(app)

    for router in (
        auth.router,
        users.router,
        parties.customers,
        parties.suppliers,
        items.raw_materials,
        items.packaging_materials,
        items.products,
        inventory.router,
        purchases.router,
        production.boms,
        production.runs,
        sales.router,
        sales.catalog_router,
        billing.invoices,
        billing.dispatches,
        billing.payments,
        billing.receivables,
        reports.router,
        dashboard.router,
        reference.router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    @app.get(f"{API_PREFIX}/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if settings.static_dir:
        _serve_frontend(app, Path(settings.static_dir))
    return app


def _serve_frontend(app: FastAPI, root: Path) -> None:
    """Serve the built React app: hashed assets with long caching, and index.html for every
    client-side route (/sales, /admin/orders/5, ...). Unknown /api paths still return JSON 404."""
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"STATIC_DIR={root} has no index.html; build the frontend first")
    root = root.resolve()
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise NotFoundError(f"No API endpoint /{path}")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):  # favicon.svg etc.
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
