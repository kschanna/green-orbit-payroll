"""Treat the canonical administration fee as a percentage.

Revision ID: e7a1c9d4b602
Revises: c42e8a71d903
"""

from alembic import op
import sqlalchemy as sa


revision = "e7a1c9d4b602"
down_revision = "c42e8a71d903"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            "UPDATE component_definitions "
            "SET calculation_type = 'percentage' "
            "WHERE code = 'ADMIN_FEE'"
        )
    )


def downgrade():
    op.execute(
        sa.text(
            "UPDATE component_definitions "
            "SET calculation_type = 'fixed' "
            "WHERE code = 'ADMIN_FEE'"
        )
    )
