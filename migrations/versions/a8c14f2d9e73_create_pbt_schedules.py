"""Create Pay, Bill & Time schedules.

Revision ID: a8c14f2d9e73
Revises: f6b29d8e4c13
"""

from alembic import op
import sqlalchemy as sa


revision = "a8c14f2d9e73"
down_revision = "f6b29d8e4c13"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pbt_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_organisation_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("generation_months", sa.Integer(), nullable=False),
        sa.Column("generated_through", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_organisation_id"], ["organisations.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pbt_schedules_customer_organisation_id",
        "pbt_schedules", ["customer_organisation_id"], unique=False,
    )

    op.create_table(
        "pbt_schedule_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pbt_schedule_id", sa.Integer(), nullable=False),
        sa.Column("schedule_type", sa.String(length=20), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=True),
        sa.Column("offset_days", sa.Integer(), nullable=False),
        sa.Column("invoice_payment_terms_days", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pbt_schedule_id"], ["pbt_schedules.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pbt_schedule_id", "schedule_type",
            name="uq_pbt_schedule_rule_type",
        ),
    )
    op.create_index(
        "ix_pbt_schedule_rules_pbt_schedule_id",
        "pbt_schedule_rules", ["pbt_schedule_id"], unique=False,
    )

    op.create_table(
        "pbt_schedule_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pbt_schedule_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("schedule_type", sa.String(length=20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("payment_terms_days", sa.Integer(), nullable=True),
        sa.Column("customer_payment_due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pbt_schedule_id"], ["pbt_schedules.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["pbt_schedule_rules.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_id", "period_start", "period_end",
            name="uq_pbt_rule_period",
        ),
    )
    op.create_index(
        "ix_pbt_schedule_periods_pbt_schedule_id",
        "pbt_schedule_periods", ["pbt_schedule_id"], unique=False,
    )
    op.create_index(
        "ix_pbt_schedule_periods_rule_id",
        "pbt_schedule_periods", ["rule_id"], unique=False,
    )
    op.create_index(
        "ix_pbt_schedule_periods_event_date",
        "pbt_schedule_periods", ["event_date"], unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_pbt_schedule_periods_event_date",
        table_name="pbt_schedule_periods",
    )
    op.drop_index(
        "ix_pbt_schedule_periods_rule_id",
        table_name="pbt_schedule_periods",
    )
    op.drop_index(
        "ix_pbt_schedule_periods_pbt_schedule_id",
        table_name="pbt_schedule_periods",
    )
    op.drop_table("pbt_schedule_periods")
    op.drop_index(
        "ix_pbt_schedule_rules_pbt_schedule_id",
        table_name="pbt_schedule_rules",
    )
    op.drop_table("pbt_schedule_rules")
    op.drop_index(
        "ix_pbt_schedules_customer_organisation_id",
        table_name="pbt_schedules",
    )
    op.drop_table("pbt_schedules")
