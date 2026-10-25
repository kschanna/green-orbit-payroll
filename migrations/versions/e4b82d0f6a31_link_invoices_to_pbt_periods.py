"""Link invoices to PBT periods and payment due dates.

Revision ID: e4b82d0f6a31
Revises: d3a71c9e5f20
"""

from alembic import op
import sqlalchemy as sa


revision = "e4b82d0f6a31"
down_revision = "d3a71c9e5f20"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoices", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column(
        "invoices",
        sa.Column("pbt_schedule_period_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_invoices_pbt_schedule_period_id",
        "invoices", "pbt_schedule_periods",
        ["pbt_schedule_period_id"], ["id"],
    )
    op.create_index(
        "ix_invoices_pbt_schedule_period_id",
        "invoices", ["pbt_schedule_period_id"], unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_invoices_pbt_schedule_period_id", table_name="invoices"
    )
    op.drop_constraint(
        "fk_invoices_pbt_schedule_period_id", "invoices", type_="foreignkey"
    )
    op.drop_column("invoices", "pbt_schedule_period_id")
    op.drop_column("invoices", "due_date")
