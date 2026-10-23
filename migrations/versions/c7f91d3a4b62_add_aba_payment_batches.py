"""Add ABA profiles, payment batches, and payment instructions.

Revision ID: c7f91d3a4b62
Revises: b6e8f4a21c70
"""

from alembic import op
import sqlalchemy as sa

revision = "c7f91d3a4b62"
down_revision = "b6e8f4a21c70"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "aba_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("financial_institution", sa.String(3), nullable=False),
        sa.Column("user_name", sa.String(26), nullable=False),
        sa.Column("apca_user_id", sa.String(6), nullable=False),
        sa.Column("file_description", sa.String(12), nullable=False),
        sa.Column("source_bsb", sa.String(6), nullable=False),
        sa.Column("source_account_number", sa.String(9), nullable=False),
        sa.Column("source_account_name", sa.String(32), nullable=False),
        sa.Column("remitter_name", sa.String(16), nullable=False),
        sa.Column("transaction_code", sa.String(2), nullable=False),
        sa.Column("balancing_entry_required", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.UniqueConstraint("organisation_id", name="uq_aba_profile_organisation"),
    )
    op.create_index("ix_aba_profiles_organisation_id", "aba_profiles", ["organisation_id"])
    op.create_table(
        "payment_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("pay_run_id", sa.Integer(), nullable=True),
        sa.Column("aba_profile_id", sa.Integer(), nullable=False),
        sa.Column("processing_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(12), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("exported_at", sa.DateTime(), nullable=True),
        sa.Column("exported_by_user_id", sa.Integer(), nullable=True),
        sa.Column("file_checksum", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["pay_run_id"], ["pay_runs.id"]),
        sa.ForeignKeyConstraint(["aba_profile_id"], ["aba_profiles.id"]),
        sa.ForeignKeyConstraint(["exported_by_user_id"], ["users.id"]),
        sa.UniqueConstraint("pay_run_id", name="uq_payment_batch_pay_run"),
    )
    op.create_index("ix_payment_batches_organisation_id", "payment_batches", ["organisation_id"])
    op.create_index("ix_payment_batches_pay_run_id", "payment_batches", ["pay_run_id"])
    op.create_table(
        "payment_instructions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_batch_id", sa.Integer(), nullable=False),
        sa.Column("payslip_id", sa.Integer(), nullable=True),
        sa.Column("worker_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("recipient_account_name", sa.String(32), nullable=False),
        sa.Column("recipient_bsb", sa.String(6), nullable=False),
        sa.Column("recipient_account_number", sa.String(9), nullable=False),
        sa.Column("transaction_code", sa.String(2), nullable=False),
        sa.Column("lodgement_reference", sa.String(18), nullable=False),
        sa.Column("trace_bsb", sa.String(6), nullable=False),
        sa.Column("trace_account_number", sa.String(9), nullable=False),
        sa.Column("remitter_name", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("manual_entry_reason", sa.String(250), nullable=True),
        sa.ForeignKeyConstraint(["payment_batch_id"], ["payment_batches.id"]),
        sa.ForeignKeyConstraint(["payslip_id"], ["payslips.id"]),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.UniqueConstraint(
            "payment_batch_id", "payslip_id",
            name="uq_payment_instruction_batch_payslip",
        ),
    )
    op.create_index("ix_payment_instructions_payment_batch_id", "payment_instructions", ["payment_batch_id"])
    op.create_index("ix_payment_instructions_payslip_id", "payment_instructions", ["payslip_id"])
    op.create_index("ix_payment_instructions_worker_id", "payment_instructions", ["worker_id"])


def downgrade():
    op.drop_table("payment_instructions")
    op.drop_table("payment_batches")
    op.drop_table("aba_profiles")
