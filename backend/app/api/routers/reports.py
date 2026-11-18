"""Reports: GET /reports (catalogue for your role), GET /reports/{key}?format=json|csv|xlsx|pdf.

Role access is declared per report in app/reports/builders.py and checked here, server side.
Default period: the 1st of the current month to today (a "monthly" report).
"""
from datetime import date
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from app.api.deps import CurrentUser, DbSession
from app.core.errors import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.reports import builders  # noqa: F401  (registers the reports)
from app.reports.exporters import to_csv, to_pdf, to_xlsx
from app.reports.framework import REGISTRY, Params, to_json
from app.services.reference import get_company

router = APIRouter(prefix="/reports", tags=["reports"])


class Format(str, Enum):
    json = "json"
    csv = "csv"
    xlsx = "xlsx"
    pdf = "pdf"


MEDIA = {
    Format.csv: "text/csv; charset=utf-8",
    Format.xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    Format.pdf: "application/pdf",
}


@router.get("")
def catalogue(user: CurrentUser) -> list[dict]:
    """Reports available to the caller's role."""
    return [{"key": d.key, "title": d.title, "description": d.description, "filters": ["date_from", "date_to", *d.params]}
            for d in REGISTRY.values() if user.role.code in d.roles]


@router.get("/{key}", responses={200: {"content": {m: {} for m in MEDIA.values()}}})
def run_report(
    key: str, db: DbSession, user: CurrentUser,
    date_from: Annotated[date | None, Query(description="Default: 1st of this month")] = None,
    date_to: Annotated[date | None, Query(description="Default: today")] = None,
    item_id: int | None = None, customer_id: int | None = None, product_id: int | None = None,
    format: Format = Format.json,  # noqa: A002 - public query parameter name
):
    definition = REGISTRY.get(key)
    if definition is None:
        raise NotFoundError(f"Unknown report '{key}'")
    if user.role.code not in definition.roles:
        raise PermissionDeniedError("Your role cannot run this report", {"report": key})
    today = date.today()
    start, end = date_from or today.replace(day=1), date_to or today
    if start > end:
        raise BusinessRuleError("date_from must be on or before date_to")
    rep = definition.builder(db, Params(start, end, item_id, customer_id, product_id, actor=user))

    if format == Format.json:
        return JSONResponse(to_json(rep))
    filename = f"{key}_{start:%Y%m%d}-{end:%Y%m%d}.{format.value}"
    if format == Format.csv:
        body = to_csv(rep)
    elif format == Format.xlsx:
        body = to_xlsx(rep)
    else:
        body = to_pdf(rep, get_company(db).legal_name)
    return Response(body, media_type=MEDIA[format], headers={"Content-Disposition": f'attachment; filename="{filename}"'})
