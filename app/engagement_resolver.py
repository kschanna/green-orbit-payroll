"""Resolve legacy Employee IDs to canonical Engagement IDs.

Transitional infrastructure. Remove after Employee retirement.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


def resolve_engagement_id(
    session: Session,
    employee_id: int,
) -> int:
    """Return the Engagement linked to a legacy Employee.

    Fail closed if no unique mapping exists.
    """
    rows = session.execute(
        text("""
            SELECT m.engagement_id
            FROM employee_engagement_migration AS m
            JOIN engagements AS e ON e.id = m.engagement_id
            WHERE m.legacy_employee_id = :employee_id
        """),
        {"employee_id": employee_id},
    ).scalars().all()

    if len(rows) != 1 or rows[0] is None:
        raise ValueError(
            f"Employee {employee_id} has no unique Engagement mapping"
        )

    return int(rows[0])


def resolve_worker_id(session: Session, employee_id: int) -> int:
    """Resolve legacy Employee to canonical Worker."""
    engagement_id = resolve_engagement_id(session, employee_id)
    worker_id = session.execute(
        text("SELECT worker_id FROM engagements WHERE id = :id"),
        {"id": engagement_id},
    ).scalar_one_or_none()

    if worker_id is None:
        raise ValueError(f"Employee {employee_id} has no Worker mapping")

    return int(worker_id)
