"""add debit and credit GLs to component mappings

Revision ID: c7a8b9c0d1e2
Revises: c6f7a8b9c0d1
"""

from alembic import op
import sqlalchemy as sa

revision = "c7a8b9c0d1e2"
down_revision = "c6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("component_gl_mappings", sa.Column(
        "debit_gl_account_id", sa.Integer(), nullable=True
    ))
    op.add_column("component_gl_mappings", sa.Column(
        "credit_gl_account_id", sa.Integer(), nullable=True
    ))
    op.create_foreign_key("fk_component_gl_mapping_debit", "component_gl_mappings",
                          "gl_accounts", ["debit_gl_account_id"], ["id"])
    op.create_foreign_key("fk_component_gl_mapping_credit", "component_gl_mappings",
                          "gl_accounts", ["credit_gl_account_id"], ["id"])
    op.execute("""
        UPDATE component_gl_mappings
        SET credit_gl_account_id = gl_account_id
        WHERE context = 'invoice_revenue'
          AND credit_gl_account_id IS NULL
    """)
    op.alter_column("component_gl_mappings", "gl_account_id",
                    existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("""
        UPDATE component_gl_mappings
        SET gl_account_id = credit_gl_account_id
        WHERE gl_account_id IS NULL
          AND context = 'invoice_revenue'
    """)
    op.execute("DELETE FROM component_gl_mappings WHERE gl_account_id IS NULL")
    op.alter_column("component_gl_mappings", "gl_account_id",
                    existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("fk_component_gl_mapping_credit", "component_gl_mappings", type_="foreignkey")
    op.drop_constraint("fk_component_gl_mapping_debit", "component_gl_mappings", type_="foreignkey")
    op.drop_column("component_gl_mappings", "credit_gl_account_id")
    op.drop_column("component_gl_mappings", "debit_gl_account_id")
