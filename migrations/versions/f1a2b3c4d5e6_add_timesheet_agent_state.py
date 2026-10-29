"""add timesheet agent state

Revision ID: f1a2b3c4d5e6
Revises: e6c7a8b9d0f1
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e6c7a8b9d0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_name", sa.String(80), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_agent_runs_agent_name", "agent_runs", ["agent_name"])
    op.create_table("agent_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_name", sa.String(80), nullable=False),
        sa.Column("issue_code", sa.String(80), nullable=False),
        sa.Column("fingerprint", sa.String(160), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("workers.id", ondelete="SET NULL")),
        sa.Column("engagement_id", sa.Integer(), sa.ForeignKey("engagements.id", ondelete="SET NULL")),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id", ondelete="SET NULL")),
        sa.Column("timesheet_header_id", sa.Integer(), sa.ForeignKey("timesheet_headers.id", ondelete="SET NULL")),
        sa.Column("task_context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    for column in ("agent_name", "issue_code", "fingerprint", "status", "worker_id"):
        op.create_index(f"ix_agent_tasks_{column}", "agent_tasks", [column])
    op.create_table("agent_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_actions_task_id", "agent_actions", ["task_id"])
    op.create_index("ix_agent_actions_run_id", "agent_actions", ["run_id"])


def downgrade() -> None:
    op.drop_table("agent_actions")
    op.drop_table("agent_tasks")
    op.drop_table("agent_runs")
