"""add financial reconciliation postings

Revision ID: c6f7a8b9c0d1
Revises: c5e6f7a8b9c0
"""

from alembic import op
import sqlalchemy as sa

revision = "c6f7a8b9c0d1"
down_revision = "c5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("gl_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False), sa.Column("role", sa.String(40)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("organisation_id", "code", name="uq_gl_account_org_code"),
        sa.UniqueConstraint("organisation_id", "role", name="uq_gl_account_org_role"))
    op.create_index("ix_gl_accounts_organisation_id", "gl_accounts", ["organisation_id"])
    op.create_table("component_gl_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("component_definition_id", sa.Integer(), sa.ForeignKey("component_definitions.id"), nullable=False),
        sa.Column("context", sa.String(30), nullable=False),
        sa.Column("gl_account_id", sa.Integer(), sa.ForeignKey("gl_accounts.id"), nullable=False),
        sa.UniqueConstraint("organisation_id", "component_definition_id", "context", name="uq_component_gl_mapping_context"))
    op.create_index("ix_component_gl_mappings_organisation_id", "component_gl_mappings", ["organisation_id"])
    op.create_index("ix_component_gl_mappings_component_definition_id", "component_gl_mappings", ["component_definition_id"])
    op.create_table("finance_postings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False), sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_reference", sa.String(120), nullable=False), sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(250), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_debits", sa.Numeric(14, 2), nullable=False), sa.Column("total_credits", sa.Numeric(14, 2), nullable=False),
        sa.Column("source_total", sa.Numeric(14, 2), nullable=False), sa.Column("balanced", sa.Boolean(), nullable=False),
        sa.Column("reconciled", sa.Boolean(), nullable=False), sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("source_type", "source_id", name="uq_finance_posting_source"),
        sa.CheckConstraint("total_debits >= 0", name="ck_finance_posting_debits_nonnegative"),
        sa.CheckConstraint("total_credits >= 0", name="ck_finance_posting_credits_nonnegative"))
    op.create_index("ix_finance_postings_organisation_id", "finance_postings", ["organisation_id"])
    op.create_index("ix_finance_postings_source_type", "finance_postings", ["source_type"])
    op.create_index("ix_finance_postings_checksum", "finance_postings", ["checksum"])
    op.create_table("finance_posting_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("posting_id", sa.Integer(), sa.ForeignKey("finance_postings.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("gl_account_id", sa.Integer(), sa.ForeignKey("gl_accounts.id")),
        sa.Column("account_code", sa.String(30), nullable=False), sa.Column("account_name", sa.String(120), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False), sa.Column("description", sa.String(250), nullable=False),
        sa.Column("debit", sa.Numeric(14, 2), nullable=False), sa.Column("credit", sa.Numeric(14, 2), nullable=False),
        sa.Column("component_definition_id", sa.Integer(), sa.ForeignKey("component_definitions.id")),
        sa.Column("component_code", sa.String(50)), sa.Column("source_line_type", sa.String(40)),
        sa.Column("source_line_id", sa.Integer()),
        sa.CheckConstraint("debit >= 0", name="ck_finance_line_debit_nonnegative"),
        sa.CheckConstraint("credit >= 0", name="ck_finance_line_credit_nonnegative"),
        sa.CheckConstraint("(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)", name="ck_finance_line_one_side"))
    op.create_index("ix_finance_posting_lines_posting_id", "finance_posting_lines", ["posting_id"])


def downgrade() -> None:
    op.drop_table("finance_posting_lines")
    op.drop_table("finance_postings")
    op.drop_table("component_gl_mappings")
    op.drop_table("gl_accounts")
