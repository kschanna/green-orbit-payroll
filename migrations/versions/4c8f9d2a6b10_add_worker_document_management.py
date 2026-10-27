"""add worker document management

Revision ID: 4c8f9d2a6b10
Revises: f5c93e1a7b42
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4c8f9d2a6b10"
down_revision: Union[str, Sequence[str], None] = "f5c93e1a7b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_worker_documents_worker_id", "worker_documents", ["worker_id"])
    op.create_index("ix_worker_documents_document_type", "worker_documents", ["document_type"])
    op.create_index("ix_worker_documents_status", "worker_documents", ["status"])
    op.create_index("ix_worker_documents_expires_on", "worker_documents", ["expires_on"])

    op.create_table(
        "document_extractions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("processor_name", sa.String(length=255), nullable=True),
        sa.Column("raw_result", sa.JSON(), nullable=False),
        sa.Column("proposed_values", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["worker_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )

    op.create_table(
        "document_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("corrected_values", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["worker_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("notification_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("action_url", sa.String(length=500), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_recipient_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("document_reviews")
    op.drop_table("document_extractions")
    op.drop_index("ix_worker_documents_expires_on", table_name="worker_documents")
    op.drop_index("ix_worker_documents_status", table_name="worker_documents")
    op.drop_index("ix_worker_documents_document_type", table_name="worker_documents")
    op.drop_index("ix_worker_documents_worker_id", table_name="worker_documents")
    op.drop_table("worker_documents")
