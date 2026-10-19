"""Add encrypted employee TFN storage and audit logging.

Revision ID: c8e29a714f60
Revises: a0f74c32fa42
"""

from alembic import op
import sqlalchemy as sa


revision = "c8e29a714f60"
down_revision = "a0f74c32fa42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "employee_tfns",
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id"),
            primary_key=True,
        ),
        sa.Column(
            "encrypted_tfn",
            sa.LargeBinary(),
            nullable=False,
        ),
        sa.Column(
            "last_three",
            sa.String(3),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "employee_tfn_audit",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(30),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_table("employee_tfn_audit")
    op.drop_table("employee_tfns")
