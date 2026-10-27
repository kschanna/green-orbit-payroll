"""backfill legacy percentage component applications

Revision ID: a23f6d8c1b04
Revises: 91ad4c7e2f10
"""

from alembic import op


revision = "a23f6d8c1b04"
down_revision = "91ad4c7e2f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The former invoice engine implicitly based every percentage component on
    # ordinary billed services. Preserve that rule as explicit assignment-level
    # dependencies, including each effective-dated ordinary configuration.
    op.execute("""
        INSERT INTO assignment_component_applications (
            assignment_component_id, source_assignment_component_id, basis
        )
        SELECT target.id, source.id, 'value'
        FROM assignment_components target
        JOIN component_definitions target_definition
          ON target_definition.id = target.component_definition_id
        JOIN assignment_components source
          ON source.assignment_id = target.assignment_id
         AND source.applies_to IN ('invoice', 'both')
        JOIN component_definitions source_definition
          ON source_definition.id = source.component_definition_id
         AND source_definition.code = 'ORDINARY_HOURS'
        WHERE target.calculation_method = 'percentage_of_value'
          AND target.applies_to IN ('invoice', 'both')
          AND NOT EXISTS (
              SELECT 1 FROM assignment_component_applications existing
              WHERE existing.assignment_component_id = target.id
          )
        ON CONFLICT ON CONSTRAINT uq_assignment_component_application DO NOTHING
    """)


def downgrade() -> None:
    # The rows are valid explicit configuration after migration and cannot be
    # distinguished safely from rows an administrator added subsequently.
    pass
