"""add ordered invoice component processing

Revision ID: 91ad4c7e2f10
Revises: 7f2c9a1d5e84
"""

from alembic import op
import sqlalchemy as sa


revision = "91ad4c7e2f10"
down_revision = "7f2c9a1d5e84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assignment_components", sa.Column("processing_stage", sa.String(30), server_default="earnings", nullable=False))
    op.add_column("assignment_components", sa.Column("processing_order", sa.Integer(), server_default="100", nullable=False))
    op.add_column("assignment_components", sa.Column("calculation_method", sa.String(40), server_default="timesheet_rate", nullable=False))
    op.add_column("assignment_components", sa.Column("unit_type", sa.String(20), server_default="hours", nullable=False))

    op.execute("""
        UPDATE assignment_components ac
        SET processing_stage = CASE cf.code
                WHEN 'FEE' THEN 'fee'
                WHEN 'ON_COST' THEN 'on_cost'
                ELSE 'earnings'
            END,
            processing_order = CASE cf.code
                WHEN 'FEE' THEN 200
                WHEN 'ON_COST' THEN 300
                ELSE 100
            END,
            calculation_method = CASE
                WHEN cd.calculation_type = 'percentage' THEN 'percentage_of_value'
                WHEN cf.code IN ('FEE', 'ON_COST') AND cd.calculation_type = 'fixed' THEN 'fixed_per_invoice'
                ELSE 'timesheet_rate'
            END
        FROM component_definitions cd
        JOIN component_families cf ON cf.id = cd.family_id
        WHERE cd.id = ac.component_definition_id
    """)

    op.create_table(
        "assignment_component_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_component_id", sa.Integer(), sa.ForeignKey("assignment_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_assignment_component_id", sa.Integer(), sa.ForeignKey("assignment_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("basis", sa.String(20), nullable=False),
        sa.UniqueConstraint("assignment_component_id", "source_assignment_component_id", name="uq_assignment_component_application"),
    )

    op.alter_column("invoice_components", "component_definition_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("invoice_components", sa.Column("assignment_component_id", sa.Integer(), sa.ForeignKey("assignment_components.id")))
    op.add_column("invoice_components", sa.Column("component_code", sa.String(50)))
    op.add_column("invoice_components", sa.Column("component_name", sa.String(150)))
    op.add_column("invoice_components", sa.Column("family_code", sa.String(50)))
    op.add_column("invoice_components", sa.Column("calculation_method", sa.String(40)))
    op.add_column("invoice_components", sa.Column("unit_type", sa.String(20)))
    op.add_column("invoice_components", sa.Column("base_amount", sa.Numeric(12, 2)))
    op.add_column("invoice_components", sa.Column("processing_order", sa.Integer()))
    op.add_column("invoice_components", sa.Column("explanation", sa.Text()))

    op.create_table(
        "invoice_component_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_component_id", sa.Integer(), sa.ForeignKey("invoice_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_invoice_component_id", sa.Integer(), sa.ForeignKey("invoice_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("basis", sa.String(20), nullable=False),
        sa.Column("source_quantity", sa.Numeric(12, 4), nullable=False),
        sa.Column("source_amount", sa.Numeric(12, 2), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("invoice_component_allocations")
    for column in ("explanation", "processing_order", "base_amount", "unit_type", "calculation_method", "family_code", "component_name", "component_code", "assignment_component_id"):
        op.drop_column("invoice_components", column)
    op.alter_column("invoice_components", "component_definition_id", existing_type=sa.Integer(), nullable=False)
    op.drop_table("assignment_component_applications")
    for column in ("unit_type", "calculation_method", "processing_order", "processing_stage"):
        op.drop_column("assignment_components", column)
