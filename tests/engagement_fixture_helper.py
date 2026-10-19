from sqlalchemy import text
from app.models.worker import Worker
from app.models.engagement import Engagement


def create_mapping_table(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE employee_engagement_migration (
                legacy_employee_id INTEGER PRIMARY KEY,
                engagement_id INTEGER NOT NULL
            )
        """))


def link_employee_to_engagement(session, employee):
    worker = Worker(
        first_name=employee.first_name,
        last_name=employee.last_name,
        email=employee.email,
    )
    session.add(worker)
    session.flush()

    engagement = Engagement(
        worker_id=worker.id,
        organisation_id=employee.organisation_id,
        engagement_type="employee",
        status="active",
    )
    session.add(engagement)
    session.flush()

    session.execute(
        text("""
            INSERT INTO employee_engagement_migration
            (legacy_employee_id, engagement_id)
            VALUES (:employee_id, :engagement_id)
        """),
        {"employee_id": employee.id, "engagement_id": engagement.id},
    )
    return engagement.id
