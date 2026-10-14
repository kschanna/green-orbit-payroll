"""Link timesheets to payslips

Revision ID: c5b2acf12fe1
Revises: 911d52e70389
"""

from alembic import op
import sqlalchemy as sa


revision = "c5b2acf12fe1"
down_revision = "911d52e70389"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payslip_timesheets",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True
        ),

        sa.Column(
            "payslip_id",
            sa.Integer(),
            sa.ForeignKey("payslips.id"),
            nullable=False
        ),

        sa.Column(
            "timesheet_id",
            sa.Integer(),
            sa.ForeignKey("timesheets.id"),
            nullable=False
        ),

        sa.UniqueConstraint(
            "payslip_id",
            "timesheet_id",
            name="uq_payslip_timesheet"
        )
    )


def downgrade():
    op.drop_table("payslip_timesheets")