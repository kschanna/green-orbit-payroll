"""link timesheets to assignments

Revision ID: ea606b53c1aa
Revises: 2f64e1f4fe75
Create Date: 2026-10-15 17:26:33.373384

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea606b53c1aa'
down_revision: Union[str, Sequence[str], None] = '2f64e1f4fe75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "timesheets",
        sa.Column("assignment_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_timesheets_assignment_id",
        "timesheets",
        "assignments",
        ["assignment_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_timesheets_assignment_id",
        "timesheets",
        type_="foreignkey",
    )
    op.drop_column("timesheets", "assignment_id")
