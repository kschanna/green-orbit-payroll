
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.assignment import Assignment
from app.models.timesheet_header import TimesheetHeader
from app.models.timesheet import Timesheet


def test_timesheet_header_without_employee():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            organisation = Organisation(
                name="Timesheet Test Organisation",
                abn="12345678901",
                country="AU",
            )
            session.add(organisation)
            session.flush()

            worker = Worker(
                first_name="Sara",
                last_name="Ali",
                email="sara.timesheet@example.com",
            )
            session.add(worker)
            session.flush()

            engagement = Engagement(
                worker_id=worker.id,
                organisation_id=organisation.id,
                engagement_type="employee",
                status="active",
            )
            session.add(engagement)
            session.flush()

            header = TimesheetHeader(
                engagement_id=engagement.id,
                employee_id=None,
                period_type="weekly",
                period_start=date(2026, 10, 12),
                period_end=date(2026, 10, 18),
                status="draft",
            )
            session.add(header)
            session.flush()

            timesheet = Timesheet(
                engagement_id=engagement.id,
                employee_id=None,
                timesheet_header_id=header.id,
                work_date=date(2026, 10, 16),
                hours_worked=Decimal("8.00"),
                status="draft",
            )
            session.add(timesheet)
            session.commit()

            assert header.employee_id is None
            assert header.engagement_id == engagement.id
            assert len(header.timesheets) == 1
            assert header.timesheets[0].id == timesheet.id

            assert session.scalar(
                select(func.count()).select_from(Worker)
            ) >= 1

    finally:
        engine.dispose()
