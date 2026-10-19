"""Create component catalogue and transaction component tables.

Revision ID: b82c6e4a19d0
Revises: f7c3a91d2b40
"""

from alembic import op
import sqlalchemy as sa

revision = "b82c6e4a19d0"
down_revision = "f7c3a91d2b40"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "component_families",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500)),
    )

    op.create_table(
        "component_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(),
                  sa.ForeignKey("component_families.id"), nullable=False),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("calculation_type", sa.String(30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
    )

    op.create_table(
        "component_bases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500)),
    )

    op.create_table(
        "component_base_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_id", sa.Integer(),
                  sa.ForeignKey("component_bases.id"), nullable=False),
        sa.Column("component_definition_id", sa.Integer(),
                  sa.ForeignKey("component_definitions.id"), nullable=False),
        sa.UniqueConstraint(
            "base_id", "component_definition_id",
            name="uq_component_base_member"
        ),
    )

    op.create_table(
        "assignment_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(),
                  sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("component_definition_id", sa.Integer(),
                  sa.ForeignKey("component_definitions.id"), nullable=False),
        sa.Column("rate", sa.Numeric(12, 4)),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
    )

    for table, parent_column, parent_table in [
        ("invoice_components", "invoice_id", "invoices"),
        ("payroll_components", "payslip_id", "payslips"),
    ]:
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(parent_column, sa.Integer(),
                      sa.ForeignKey(f"{parent_table}.id"), nullable=False),
            sa.Column("component_definition_id", sa.Integer(),
                      sa.ForeignKey("component_definitions.id"),
                      nullable=False),
            sa.Column("quantity", sa.Numeric(12, 4), nullable=False),
            sa.Column("rate", sa.Numeric(12, 4), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        )

    op.create_table(
        "component_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("component_definition_id", sa.Integer(),
                  sa.ForeignKey("component_definitions.id")),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("details", sa.String(2000)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    for table in [
        "component_audit_log",
        "payroll_components",
        "invoice_components",
        "assignment_components",
        "component_base_members",
        "component_bases",
        "component_definitions",
        "component_families",
    ]:
        op.drop_table(table)
