"""add GST paid payroll component

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""

from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    tax_family_id = connection.execute(sa.text(
        "SELECT id FROM component_families WHERE code = 'TAX'"
    )).scalar_one()
    connection.execute(sa.text("""
        INSERT INTO component_definitions
            (family_id, code, name, description, calculation_type, active)
        VALUES
            (:family_id, 'GST_PAID', 'GST Paid',
             'GST added to a company contractor payment', 'percentage', true)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            calculation_type = EXCLUDED.calculation_type,
            active = true
    """), {"family_id": tax_family_id})


def downgrade() -> None:
    op.execute("DELETE FROM component_definitions WHERE code = 'GST_PAID'")
