"""Add engagement leave plans and immutable leave ledger.

Revision ID: a4d7c2e91f30
Revises: f3b6a91d2c44
"""

from alembic import op
import sqlalchemy as sa


revision = "a4d7c2e91f30"
down_revision = "f3b6a91d2c44"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "leave_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("workers.id"), nullable=False),
        sa.Column("engagement_id", sa.Integer(), sa.ForeignKey("engagements.id"), nullable=False),
        sa.Column("component_definition_id", sa.Integer(), sa.ForeignKey("component_definitions.id"), nullable=False),
        sa.Column("annual_entitlement_hours", sa.Numeric(10, 4), nullable=False),
        sa.Column("standard_hours_per_year", sa.Numeric(10, 4), nullable=False),
        sa.Column("accrual_rate_per_hour", sa.Numeric(14, 10), nullable=False),
        sa.Column("opening_balance_hours", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("allow_negative_balance", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("accrues_during_paid_leave", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.UniqueConstraint("engagement_id", "component_definition_id", "effective_from", name="uq_leave_plan_effective_from"),
    )
    op.create_index("ix_leave_plans_worker_id", "leave_plans", ["worker_id"])
    op.create_index("ix_leave_plans_engagement_id", "leave_plans", ["engagement_id"])
    op.create_index("ix_leave_plans_component_definition_id", "leave_plans", ["component_definition_id"])
    op.create_table(
        "leave_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("leave_plan_id", sa.Integer(), sa.ForeignKey("leave_plans.id"), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("transaction_type", sa.String(30), nullable=False),
        sa.Column("hours", sa.Numeric(12, 4), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(300)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("leave_plan_id", "source_type", "source_id", "transaction_type", name="uq_leave_transaction_source"),
    )
    op.create_index("ix_leave_transactions_leave_plan_id", "leave_transactions", ["leave_plan_id"])


def downgrade():
    op.drop_index("ix_leave_transactions_leave_plan_id", table_name="leave_transactions")
    op.drop_table("leave_transactions")
    op.drop_index("ix_leave_plans_component_definition_id", table_name="leave_plans")
    op.drop_index("ix_leave_plans_engagement_id", table_name="leave_plans")
    op.drop_index("ix_leave_plans_worker_id", table_name="leave_plans")
    op.drop_table("leave_plans")
