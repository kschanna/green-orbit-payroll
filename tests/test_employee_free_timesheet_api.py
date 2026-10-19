
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.assignment import Assignment
from app.models.timesheet_header import TimesheetHeader
from app.models.timesheet import Timesheet

from app.main import (
    TimesheetCreate,
    WeeklyTimesheetCreate,
    WeeklyTimesheetEntry,
    create_timesheet,
    update_timesheet,
    create_weekly_timesheet,
    update_weekly_timesheet,
)


@pytest.fixture
def data():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with patch("app.main.SessionLocal", factory):
        with Session(engine) as db:
            organisation = Organisation(
                name="Timesheet API Test",
                abn="12345678901",
                country="AU",
            )
            customer = Organisation(
                name="Timesheet API Customer",
                abn="98765432109",
                country="AU",
            )
            db.add_all([organisation, customer])
            db.flush()

            worker = Worker(
                first_name="Sara",
                last_name="Ali",
                email="sara.timesheet.api@example.com",
            )
            db.add(worker)
            db.flush()

            engagement = Engagement(
                worker_id=worker.id,
                organisation_id=organisation.id,
                engagement_type="employee",
                status="active",
            )
            db.add(engagement)
            db.flush()

            assignment = Assignment(
                engagement_id=engagement.id,
                employee_id=None,
                customer_id=customer.id,
                billing_rate=Decimal("100.00"),
            )
            db.add(assignment)
            db.commit()

            ids = (engagement.id, assignment.id)

        yield engine, ids

    engine.dispose()


def test_employee_free_daily_create_update(data):
    engine, (engagement_id, assignment_id) = data

    result = create_timesheet(
        TimesheetCreate(
            engagement_id=engagement_id,
            assignment_id=assignment_id,
            work_date=date(2026, 10, 16),
            hours_worked=Decimal("8.00"),
        )
    )

    assert result["engagement_id"] == engagement_id

    update_timesheet(
        result["id"],
        TimesheetCreate(
            engagement_id=engagement_id,
            assignment_id=assignment_id,
            work_date=date(2026, 10, 16),
            hours_worked=Decimal("7.50"),
        ),
    )

    with Session(engine) as db:
        row = db.get(Timesheet, result["id"])
        assert row.employee_id is None
        assert row.hours_worked == Decimal("7.50")
        assert db.scalar(
            select(func.count()).select_from(Worker)
        ) >= 1


def test_employee_free_weekly_create_update(data):
    engine, (engagement_id, assignment_id) = data

    monday = date(2026, 10, 12)

    def payload(hours):
        return WeeklyTimesheetCreate(
            engagement_id=engagement_id,
            week_start=monday,
            entries=[
                WeeklyTimesheetEntry(
                    work_date=monday + timedelta(days=i),
                    assignment_id=assignment_id,
                    hours_worked=Decimal(hours),
                )
                for i in range(7)
            ],
        )

    result = create_weekly_timesheet(payload("8.00"))

    assert result["days_created"] == 7

    update_weekly_timesheet(
        result["timesheet_header_id"],
        payload("7.00"),
    )

    with Session(engine) as db:
        header = db.get(
            TimesheetHeader,
            result["timesheet_header_id"],
        )
        assert header.employee_id is None
        assert header.engagement_id == engagement_id
        assert len(header.timesheets) == 7
        assert all(
            t.employee_id is None
            and t.engagement_id == engagement_id
            and t.hours_worked == Decimal("7.00")
            for t in header.timesheets
        )


def test_cross_engagement_assignment_rejected(data):
    engine, (engagement_id, assignment_id) = data

    with Session(engine) as db:
        original = db.get(Engagement, engagement_id)

        other_engagement = Engagement(
            worker_id=original.worker_id,
            organisation_id=original.organisation_id,
            engagement_type="employee",
            status="active",
        )
        db.add(other_engagement)
        db.commit()
        other_engagement_id = other_engagement.id

    with pytest.raises(
        HTTPException,
        match="Selected assignment does not belong",
    ):
        create_timesheet(
            TimesheetCreate(
                engagement_id=other_engagement_id,
                assignment_id=assignment_id,
                work_date=date(2026, 10, 16),
                hours_worked=Decimal("8.00"),
            )
        )
