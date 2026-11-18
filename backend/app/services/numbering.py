"""Document numbers per financial year, e.g. INV/2026-27/00001.

The sequence row is locked (SELECT ... FOR UPDATE) for the rest of the transaction,
so two concurrent invoices can never get the same number; and because the increment
is part of the same transaction as the document, a rolled-back document does not
burn a number (gap-free).
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CompanyProfile, DocumentSequence
from app.models.enums import DocumentType

PREFIXES: dict[DocumentType, str] = {
    DocumentType.SALES_ORDER: "SO",
    DocumentType.INVOICE: "INV",
    DocumentType.CREDIT_NOTE: "CN",
    DocumentType.DISPATCH: "DSP",
    DocumentType.PURCHASE: "PUR",
    DocumentType.PRODUCTION_RUN: "PRD",
    DocumentType.RECEIPT: "RCP",
    DocumentType.STOCK_ADJUSTMENT: "ADJ",
}


@dataclass(frozen=True)
class DocNumber:
    number: str  # INV/2026-27/00001
    financial_year: str  # 2026-27
    sequence: int  # 1


def financial_year(on: date, fy_start_month: int = 4) -> str:
    """Indian FY runs April-March: 2026-11-18 -> '2026-27', 2027-02-01 -> '2026-27'."""
    start = on.year if on.month >= fy_start_month else on.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def next_number(db: Session, doc_type: DocumentType, on: date) -> DocNumber:
    company = db.get(CompanyProfile, 1)
    fy = financial_year(on, company.fy_start_month if company else 4)
    _ensure_sequence(db, doc_type, fy)
    seq = db.scalars(
        select(DocumentSequence)
        .where(DocumentSequence.doc_type == doc_type, DocumentSequence.financial_year == fy)
        .with_for_update().execution_options(populate_existing=True)
    ).one()
    seq.last_number += 1
    db.flush()
    return DocNumber(f"{seq.prefix}/{fy}/{seq.last_number:05d}", fy, seq.last_number)


def _ensure_sequence(db: Session, doc_type: DocumentType, fy: str) -> None:
    """Create the year's sequence row if missing, race-free: when two transactions start a new
    financial year at once, the second waits on the unique key and then does nothing, instead
    of failing with a duplicate-key error."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover
        raise RuntimeError(f"Unsupported database: {dialect}")
    db.execute(
        insert(DocumentSequence)
        .values(doc_type=doc_type, financial_year=fy, prefix=PREFIXES[doc_type], last_number=0)
        .on_conflict_do_nothing(index_elements=["doc_type", "financial_year"])
    )
