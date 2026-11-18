"""Add STOCK_ADJUSTMENT to the document numbering series.

Enums are stored as VARCHAR + CHECK, so extending one is a constraint swap.
(Alembic autogenerate does not detect enum value changes; written by hand.)

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("SALES_ORDER", "INVOICE", "CREDIT_NOTE", "DISPATCH", "PURCHASE", "PRODUCTION_RUN", "RECEIPT")
_NEW = (*_OLD, "STOCK_ADJUSTMENT")
# Name produced by the naming convention ck_%(table_name)s_%(constraint_name)s.
_NAME = "documenttype"


def _swap(values: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{v}'" for v in values)
    with op.batch_alter_table("document_sequences") as batch:
        batch.drop_constraint(op.f(f"ck_document_sequences_{_NAME}"), type_="check")
        batch.create_check_constraint(op.f(f"ck_document_sequences_{_NAME}"), f"doc_type IN ({allowed})")


def upgrade() -> None:
    _swap(_NEW)


def downgrade() -> None:
    op.execute("DELETE FROM document_sequences WHERE doc_type = 'STOCK_ADJUSTMENT'")
    _swap(_OLD)
