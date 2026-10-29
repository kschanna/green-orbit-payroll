"""add payroll readiness runs

Revision ID: e6c7a8b9d0f1
Revises: a23f6d8c1b04
"""
from alembic import op
import sqlalchemy as sa

revision = "e6c7a8b9d0f1"
down_revision = "a23f6d8c1b04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payroll_readiness_runs",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("triggered_by_user_id", sa.Integer(), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False), sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False), sa.Column("critical_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["triggered_by_user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payroll_readiness_runs_triggered_by_user_id", "payroll_readiness_runs", ["triggered_by_user_id"])
    op.create_index("ix_payroll_readiness_runs_as_of", "payroll_readiness_runs", ["as_of"])
    op.create_index("ix_payroll_readiness_runs_fingerprint", "payroll_readiness_runs", ["fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_payroll_readiness_runs_fingerprint", table_name="payroll_readiness_runs")
    op.drop_index("ix_payroll_readiness_runs_as_of", table_name="payroll_readiness_runs")
    op.drop_index("ix_payroll_readiness_runs_triggered_by_user_id", table_name="payroll_readiness_runs")
    op.drop_table("payroll_readiness_runs")
