"""FastAPI application entry point: `uvicorn app.main:app --reload`."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, billing, dashboard, inventory, items, parties, production, purchases, reference, reports, sales, users
from app.core.config import get_settings
from app.core.errors import register_exception_handlers

API_PREFIX = "/api"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Order-to-Audit System",
        version="0.8.0",
        description="Sales → Verification → GST Invoice → Dispatch → Inventory → Production → Costing → Audit",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
        swagger_ui_oauth2_redirect_url=f"{API_PREFIX}/docs/oauth2-redirect",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origin_list,
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

    return app


app = create_app()
