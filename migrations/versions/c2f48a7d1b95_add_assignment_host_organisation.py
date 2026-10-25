"""Add assignment host organisation.

Revision ID: c2f48a7d1b95
Revises: b9d27e4a6f81
"""

from alembic import op
import sqlalchemy as sa


revision = "c2f48a7d1b95"
down_revision = "b9d27e4a6f81"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignments",
        sa.Column("host_organisation_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_assignments_host_organisation_id",
        "assignments",
        "organisations",
        ["host_organisation_id"],
        ["id"],
    )
    op.create_index(
        "ix_assignments_host_organisation_id",
        "assignments",
        ["host_organisation_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_assignments_host_organisation_id",
        table_name="assignments",
    )
    op.drop_constraint(
        "fk_assignments_host_organisation_id",
        "assignments",
        type_="foreignkey",
    )
    op.drop_column("assignments", "host_organisation_id")
