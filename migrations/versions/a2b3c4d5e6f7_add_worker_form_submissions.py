"""add encrypted worker form submissions

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "worker_form_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.Integer(), sa.ForeignKey("workers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submitted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("form_type", sa.String(50), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("submission_metadata", sa.JSON(), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("declaration_hash", sa.String(64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_notes", sa.Text()),
    )
    op.create_index("ix_worker_form_submissions_worker_id", "worker_form_submissions", ["worker_id"])
    op.create_index("ix_worker_form_submissions_form_type", "worker_form_submissions", ["form_type"])
    op.create_index("ix_worker_form_submissions_status", "worker_form_submissions", ["status"])


def downgrade():
    op.drop_table("worker_form_submissions")
