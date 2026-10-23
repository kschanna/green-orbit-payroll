"""Support contractual contractor leave plans and timesheet links.

Revision ID: b6e8f4a21c70
Revises: a4d7c2e91f30
"""

from alembic import op
import sqlalchemy as sa

revision = "b6e8f4a21c70"
down_revision = "a4d7c2e91f30"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "leave_plans",
        sa.Column("plan_basis", sa.String(30), nullable=False,
                  server_default="statutory"),
    )
    op.add_column(
        "leave_plans",
        sa.Column("paid_leave_rate", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "timesheets",
        sa.Column("leave_plan_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_timesheets_leave_plan_id",
        "timesheets", "leave_plans", ["leave_plan_id"], ["id"],
    )
    op.create_index(
        "ix_timesheets_leave_plan_id", "timesheets", ["leave_plan_id"]
    )


def downgrade():
    op.drop_index("ix_timesheets_leave_plan_id", table_name="timesheets")
    op.drop_constraint(
        "fk_timesheets_leave_plan_id", "timesheets", type_="foreignkey"
    )
    op.drop_column("timesheets", "leave_plan_id")
    op.drop_column("leave_plans", "paid_leave_rate")
    op.drop_column("leave_plans", "plan_basis")
