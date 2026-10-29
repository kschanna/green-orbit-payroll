from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.main as main_module
from app.models.engagement import Engagement
from app.models.organisation import Base, Organisation
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.worker import Worker


def test_timesheet_screen_filters_period_and_daily_rows_by_person(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with Session(engine) as db:
        organisation = Organisation(name="Employer", abn="12345678901", country="AU")
        alex = Worker(first_name="Alex", last_name="Filtered", email="alex-filter@example.com")
        jordan = Worker(first_name="Jordan", last_name="Hidden", email="jordan-hidden@example.com")
        db.add_all([organisation, alex, jordan])
        db.flush()
        alex_engagement = Engagement(
            worker_id=alex.id, organisation_id=organisation.id,
            engagement_type="employee", status="active",
        )
        jordan_engagement = Engagement(
            worker_id=jordan.id, organisation_id=organisation.id,
            engagement_type="employee", status="active",
        )
        db.add_all([alex_engagement, jordan_engagement])
        db.flush()
        for engagement, name_date in (
            (alex_engagement, date(2026, 10, 20)),
            (jordan_engagement, date(2026, 10, 21)),
        ):
            header = TimesheetHeader(
                engagement_id=engagement.id, period_type="weekly",
                period_start=name_date, period_end=name_date,
                status="draft", source="manual",
            )
            db.add(header)
            db.flush()
            db.add(Timesheet(
                engagement_id=engagement.id, timesheet_header_id=header.id,
                work_date=name_date, hours_worked=Decimal("8"), status="draft",
            ))
            db.add(Timesheet(
                engagement_id=engagement.id, work_date=name_date,
                hours_worked=Decimal("1"), status="draft",
            ))
        db.commit()
        alex_id = alex.id

    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    request = Request({
        "type": "http", "method": "GET", "path": "/ui/timesheets",
        "query_string": f"worker_id={alex_id}".encode(), "headers": [],
        "session": {"user_id": 1, "csrf_token": "test"},
    })
    response = main_module.list_timesheets(request, worker_id=alex_id)
    html = response.body.decode()

    assert "Alex Filtered" in html
    assert "Jordan Hidden" in html  # Still available as a filter option.
    assert html.count("Alex Filtered") >= 3  # Option, period row, daily row.
    assert html.count("Jordan Hidden") == 1
    assert f"worker_id={alex_id}" in html  # Pagination retains the filter.
