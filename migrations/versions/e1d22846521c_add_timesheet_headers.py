"""add timesheet headers

Revision ID: e1d22846521c
Revises: a940c52eb3a7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1d22846521c"
down_revision: Union[str, Sequence[str], None] = "a940c52eb3a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timesheet_headers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id"),
            nullable=False
        ),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
    )

    op.add_column(
        "timesheets",
        sa.Column("timesheet_header_id", sa.Integer(), nullable=True)
    )

    op.create_foreign_key(
        "fk_timesheets_timesheet_header_id",
        "timesheets",
        "timesheet_headers",
        ["timesheet_header_id"],
        ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_timesheets_timesheet_header_id",
        "timesheets",
        type_="foreignkey"
    )

    op.drop_column("timesheets", "timesheet_header_id")

    op.drop_table("timesheet_headers")