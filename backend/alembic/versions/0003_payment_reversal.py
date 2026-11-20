"""Payment reversal: receipts are reversed (bounced cheque, failed transfer), never deleted.

Revision ID: 0003
Revises: 0002
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = (
    "(reversed_on IS NULL AND reversal_reason IS NULL AND reversed_by IS NULL AND reversed_at IS NULL)"
    " OR (reversed_on IS NOT NULL AND reversal_reason IS NOT NULL AND reversed_by IS NOT NULL"
    " AND reversed_at IS NOT NULL AND reversed_on >= payment_date)"
)


def upgrade() -> None:
    with op.batch_alter_table("payments") as batch:
        batch.add_column(sa.Column("reversed_on", sa.Date(), nullable=True))
        batch.add_column(sa.Column("reversal_reason", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("reversed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(op.f("fk_payments_reversed_by_users"), "users", ["reversed_by"], ["id"])
        batch.create_index(op.f("ix_payments_reversed_on"), ["reversed_on"])
        batch.create_check_constraint(op.f("ck_payments_reversal_complete"), _CHECK)


def downgrade() -> None:
    with op.batch_alter_table("payments") as batch:
        batch.drop_constraint(op.f("ck_payments_reversal_complete"), type_="check")
        batch.drop_index(op.f("ix_payments_reversed_on"))
        batch.drop_constraint(op.f("fk_payments_reversed_by_users"), type_="foreignkey")
        batch.drop_column("reversed_at")
        batch.drop_column("reversed_by")
        batch.drop_column("reversal_reason")
        batch.drop_column("reversed_on")
