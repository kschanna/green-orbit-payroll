"""add worker portal accounts

Revision ID: 7f2c9a1d5e84
Revises: 4c8f9d2a6b10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f2c9a1d5e84"
down_revision: Union[str, Sequence[str], None] = "4c8f9d2a6b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), server_default="admin", nullable=False),
    )
    op.add_column("users", sa.Column("worker_id", sa.Integer(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_users_worker_id", "users", "workers", ["worker_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint("uq_users_worker_id", "users", ["worker_id"])


def downgrade() -> None:
    op.drop_constraint("uq_users_worker_id", "users", type_="unique")
    op.drop_constraint("fk_users_worker_id", "users", type_="foreignkey")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "worker_id")
    op.drop_column("users", "role")
