from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.main  # noqa: F401
import app.timesheet_run_router as run_router
from app.models.assignment import Assignment
from app.models.engagement import Engagement
from app.models.organisation import Base, Organisation
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.pbt_schedule_rule import PBTScheduleRule
from app.models.worker import Worker
from app.timesheet_run_router import TimesheetRunCreate, TimesheetRunSelection


def test_timesheet_run_person_filter_limits_rows_and_survives_pagination(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with Session(engine) as db:
        employer = Organisation(name="Employer", abn="12345678901", country="AU")
        customer = Organisation(name="Customer", abn="98765432109", country="AU")
        alex = Worker(first_name="Alex", last_name="Selected", email="alex-run@example.com")
        jordan = Worker(first_name="Jordan", last_name="Excluded", email="jordan-run@example.com")
        db.add_all([employer, customer, alex, jordan])
        db.flush()
        schedule = PBTSchedule(
            customer_organisation_id=customer.id, name="Weekly",
            effective_from=date(2026, 1, 1), status="active",
        )
        db.add(schedule)
        db.flush()
        rule = PBTScheduleRule(
            pbt_schedule_id=schedule.id, schedule_type="timesheet",
            frequency="weekly", anchor_date=date(2026, 10, 19),
            offset_days=1, active=True,
        )
        db.add(rule)
        db.flush()
        period = PBTSchedulePeriod(
            pbt_schedule_id=schedule.id, rule_id=rule.id,
            schedule_type="timesheet", period_start=date(2026, 10, 19),
            period_end=date(2026, 10, 25), event_date=date(2026, 10, 26),
        )
        db.add(period)
        for worker in (alex, jordan):
            engagement = Engagement(
                worker_id=worker.id, organisation_id=employer.id,
                engagement_type="employee", status="active",
            )
            db.add(engagement)
            db.flush()
            assignment = Assignment(
                engagement_id=engagement.id, customer_id=customer.id,
                pbt_schedule_id=schedule.id, billing_rate=Decimal("100"),
            )
            db.add(assignment)
            db.flush()
            if worker is alex:
                alex_assignment_id = assignment.id
        db.commit()
        alex_id = alex.id
        period_id = period.id

    monkeypatch.setattr(run_router, "SessionLocal", factory)
    request = Request({
        "type": "http", "method": "GET", "path": "/ui/timesheet-runs",
        "query_string": f"worker_id={alex_id}".encode(), "headers": [],
        "session": {"user_id": 1, "csrf_token": "test"},
    })
    response = run_router.timesheet_run_page(
        request, worker_id=str(alex_id), customer_id="",
        date_from=date(2026, 10, 1), date_to=date(2026, 10, 31),
    )
    html = response.body.decode()

    assert html.count("Alex Selected") >= 2  # Filter option and result row.
    assert html.count("Jordan Excluded") == 1  # Filter option only.
    assert f"worker_id={alex_id}" in html

    result = run_router.create_timesheet_run(TimesheetRunCreate(selections=[
        TimesheetRunSelection(
            assignment_id=alex_assignment_id,
            pbt_schedule_period_id=period_id,
        )
    ]))
    assert result["agent_alert"]["code"] == "missing_tfn_declaration"
