"""Link assignments to PBT schedules.

Revision ID: b9d27e4a6f81
Revises: a8c14f2d9e73
"""

from alembic import op
import sqlalchemy as sa


revision = "b9d27e4a6f81"
down_revision = "a8c14f2d9e73"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignments",
        sa.Column("pbt_schedule_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_assignments_pbt_schedule_id",
        "assignments",
        "pbt_schedules",
        ["pbt_schedule_id"],
        ["id"],
    )
    op.create_index(
        "ix_assignments_pbt_schedule_id",
        "assignments",
        ["pbt_schedule_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_assignments_pbt_schedule_id",
        table_name="assignments",
    )
    op.drop_constraint(
        "fk_assignments_pbt_schedule_id",
        "assignments",
        type_="foreignkey",
    )
    op.drop_column("assignments", "pbt_schedule_id")
