"""assignment component dual rates

Revision ID: 2f64e1f4fe75
Revises: d91b6e42a703
Create Date: 2026-10-15 16:59:05.018261

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f64e1f4fe75'
down_revision: Union[str, Sequence[str], None] = 'd91b6e42a703'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "assignment_components",
        sa.Column("pay_rate", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "assignment_components",
        sa.Column("bill_rate", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "assignment_components",
        sa.Column(
            "applies_to",
            sa.String(20),
            nullable=False,
            server_default="payroll",
        ),
    )

    op.execute(
        "UPDATE assignment_components "
        "SET pay_rate = rate, applies_to = 'payroll'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("assignment_components", "applies_to")
    op.drop_column("assignment_components", "bill_rate")
    op.drop_column("assignment_components", "pay_rate")
