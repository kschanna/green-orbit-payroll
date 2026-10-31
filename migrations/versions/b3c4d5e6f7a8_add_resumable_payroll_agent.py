"""add resumable payroll agent runs and steps

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""
from alembic import op
import sqlalchemy as sa

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payroll_agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("workers.id"), nullable=False),
        sa.Column("pbt_schedule_period_id", sa.Integer(), sa.ForeignKey("pbt_schedule_periods.id"), nullable=False),
        sa.Column("triggered_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("current_step", sa.String(80), nullable=False),
        sa.Column("blockers", sa.JSON(), nullable=False),
        sa.Column("records", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for column in ("assignment_id", "worker_id", "pbt_schedule_period_id", "status"):
        op.create_index(f"ix_payroll_agent_runs_{column}", "payroll_agent_runs", [column])
    op.create_table(
        "payroll_agent_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_key", sa.String(80), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("decision_source", sa.String(30), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("run_id", "step_key", name="uq_payroll_agent_run_step"),
    )
    op.create_index("ix_payroll_agent_steps_run_id", "payroll_agent_steps", ["run_id"])
    op.create_index("ix_payroll_agent_steps_status", "payroll_agent_steps", ["status"])


def downgrade():
    op.drop_table("payroll_agent_steps")
    op.drop_table("payroll_agent_runs")
