"""Add scheduled timesheet links.

Revision ID: d3a71c9e5f20
Revises: c2f48a7d1b95
"""

from alembic import op
import sqlalchemy as sa


revision = "d3a71c9e5f20"
down_revision = "c2f48a7d1b95"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "timesheet_headers",
        sa.Column("assignment_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "timesheet_headers",
        sa.Column("pbt_schedule_period_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "timesheet_headers",
        sa.Column(
            "source", sa.String(length=20),
            nullable=False, server_default="manual",
        ),
    )
    op.create_foreign_key(
        "fk_timesheet_headers_assignment_id",
        "timesheet_headers", "assignments", ["assignment_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_timesheet_headers_pbt_schedule_period_id",
        "timesheet_headers", "pbt_schedule_periods",
        ["pbt_schedule_period_id"], ["id"],
    )
    op.create_index(
        "ix_timesheet_headers_assignment_id",
        "timesheet_headers", ["assignment_id"], unique=False,
    )
    op.create_index(
        "ix_timesheet_headers_pbt_schedule_period_id",
        "timesheet_headers", ["pbt_schedule_period_id"], unique=False,
    )
    op.create_unique_constraint(
        "uq_timesheet_header_assignment_pbt_period",
        "timesheet_headers", ["assignment_id", "pbt_schedule_period_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_timesheet_header_assignment_pbt_period",
        "timesheet_headers", type_="unique",
    )
    op.drop_index(
        "ix_timesheet_headers_pbt_schedule_period_id",
        table_name="timesheet_headers",
    )
    op.drop_index(
        "ix_timesheet_headers_assignment_id",
        table_name="timesheet_headers",
    )
    op.drop_constraint(
        "fk_timesheet_headers_pbt_schedule_period_id",
        "timesheet_headers", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_timesheet_headers_assignment_id",
        "timesheet_headers", type_="foreignkey",
    )
    op.drop_column("timesheet_headers", "source")
    op.drop_column("timesheet_headers", "pbt_schedule_period_id")
    op.drop_column("timesheet_headers", "assignment_id")
