"""Add component allocations to timesheet rows.

Revision ID: f3b6a91d2c44
Revises: e7a1c9d4b602
"""

from alembic import op
import sqlalchemy as sa


revision = "f3b6a91d2c44"
down_revision = "e7a1c9d4b602"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "timesheets",
        sa.Column("component_definition_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_timesheets_component_definition_id",
        "timesheets",
        "component_definitions",
        ["component_definition_id"],
        ["id"],
    )
    op.create_index(
        "ix_timesheets_component_definition_id",
        "timesheets",
        ["component_definition_id"],
    )


def downgrade():
    op.drop_index(
        "ix_timesheets_component_definition_id",
        table_name="timesheets",
    )
    op.drop_constraint(
        "fk_timesheets_component_definition_id",
        "timesheets",
        type_="foreignkey",
    )
    op.drop_column("timesheets", "component_definition_id")
