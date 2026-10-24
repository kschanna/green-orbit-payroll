"""Backfill assignment Ordinary Hours bill rates.

Revision ID: d4e8a1c72b90
Revises: c7f91d3a4b62
"""

from alembic import op


revision = "d4e8a1c72b90"
down_revision = "c7f91d3a4b62"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE assignment_components AS component
        SET
            bill_rate = assignment.billing_rate,
            applies_to = 'both'
        FROM assignments AS assignment,
             component_definitions AS ordinary
        WHERE component.assignment_id = assignment.id
          AND component.component_definition_id = ordinary.id
          AND ordinary.code = 'ORDINARY_HOURS'
          AND component.applies_to = 'payroll'
          AND component.bill_rate IS NULL
        """
    )

    op.execute(
        """
        INSERT INTO assignment_components (
            assignment_id,
            component_definition_id,
            rate,
            pay_rate,
            bill_rate,
            applies_to,
            effective_from,
            effective_to
        )
        SELECT
            assignment.id,
            ordinary.id,
            NULL,
            NULL,
            assignment.billing_rate,
            'invoice',
            COALESCE(
                engagement.start_date,
                (
                    SELECT MIN(timesheet.work_date)
                    FROM timesheets AS timesheet
                    WHERE timesheet.assignment_id = assignment.id
                ),
                CURRENT_DATE
            ),
            NULL
        FROM assignments AS assignment
        JOIN engagements AS engagement
          ON engagement.id = assignment.engagement_id
        CROSS JOIN component_definitions AS ordinary
        WHERE ordinary.code = 'ORDINARY_HOURS'
          AND NOT EXISTS (
              SELECT 1
              FROM assignment_components AS existing
              WHERE existing.assignment_id = assignment.id
                AND existing.component_definition_id = ordinary.id
          )
        """
    )


def downgrade():
    # This migration creates business configuration records. They are retained
    # on downgrade because they cannot be distinguished safely from records a
    # user may subsequently edit in the application.
    pass
