"""Add optional assignment start and end dates.

Revision ID: f6b29d8e4c13
Revises: d4e8a1c72b90
"""

from alembic import op
import sqlalchemy as sa


revision = "f6b29d8e4c13"
down_revision = "d4e8a1c72b90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignments",
        sa.Column("start_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "assignments",
        sa.Column("end_date", sa.Date(), nullable=True),
    )
    op.execute(
        "UPDATE assignments "
        "SET start_date = DATE '2026-01-01' "
        "WHERE start_date IS NULL"
    )


def downgrade():
    op.drop_column("assignments", "end_date")
    op.drop_column("assignments", "start_date")
