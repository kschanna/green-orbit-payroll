"""Rename employment agreements and worker engagements

Revision ID: f7c3a91d2b40
Revises: e1d22846521c
"""

from alembic import op

revision = "f7c3a91d2b40"
down_revision = "e1d22846521c"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("employment_agreements", "work_patterns")
    op.rename_table("worker_engagements", "assignments")


def downgrade():
    op.rename_table("assignments", "worker_engagements")
    op.rename_table("work_patterns", "employment_agreements")
