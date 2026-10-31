"""store immutable ABA file exports

Revision ID: c5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""

from alembic import op
import sqlalchemy as sa


revision = "c5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aba_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "payment_batch_id", sa.Integer(),
            sa.ForeignKey("payment_batches.id"), nullable=False,
        ),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_by_user_id", sa.Integer(),
            sa.ForeignKey("users.id"), nullable=True,
        ),
    )
    op.create_index(
        "ix_aba_files_payment_batch_id", "aba_files", ["payment_batch_id"]
    )
    op.create_index("ix_aba_files_checksum", "aba_files", ["checksum"])


def downgrade() -> None:
    op.drop_table("aba_files")
