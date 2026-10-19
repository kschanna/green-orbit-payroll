"""Add employee payment bank details.

Revision ID: d91b6e42a703
Revises: c8e29a714f60
"""

from alembic import op
import sqlalchemy as sa

revision = "d91b6e42a703"
down_revision = "c8e29a714f60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "employee_payment_details",
        sa.Column("account_name", sa.String(200), nullable=True),
    )
    op.add_column(
        "employee_payment_details",
        sa.Column("bsb", sa.String(6), nullable=True),
    )
    op.add_column(
        "employee_payment_details",
        sa.Column("account_number", sa.String(20), nullable=True),
    )


def downgrade():
    op.drop_column("employee_payment_details", "account_number")
    op.drop_column("employee_payment_details", "bsb")
    op.drop_column("employee_payment_details", "account_name")
