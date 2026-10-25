import uuid
from datetime import date

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.assignment import Assignment
from app.models.engagement import Engagement
from app.models.invoice import Invoice
from app.models.organisation import Organisation
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.pbt_schedule_rule import PBTScheduleRule
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.worker import Worker
from app.timesheet_run_router import (
    TimesheetRunCreate,
    TimesheetRunSelection,
    create_timesheet_run,
    approve_scheduled_timesheet,
)
from app.main import TimesheetInvoiceInput, create_invoice_from_timesheet


def _seed_expected_period():
    token = uuid.uuid4().hex
    with SessionLocal() as db:
        organisation = Organisation(
            name=f"Timesheet Run {token[:8]}",
            abn=str(uuid.uuid4().int % 100_000_000_000).zfill(11),
            country="AU",
        )
        worker = Worker(
            first_name="Schedule",
            last_name="Tester",
            email=f"schedule-{token}@example.com",
        )
        db.add_all([organisation, worker])
        db.flush()
        engagement = Engagement(
            worker_id=worker.id,
            organisation_id=organisation.id,
            engagement_type="payg_employee",
            status="active",
            start_date=date(2026, 1, 1),
        )
        schedule = PBTSchedule(
            customer_organisation_id=organisation.id,
            name=f"Fortnightly {token[:8]}",
            effective_from=date(2026, 1, 1),
            status="active",
            generation_months=12,
        )
        db.add_all([engagement, schedule])
        db.flush()
        assignment = Assignment(
            engagement_id=engagement.id,
            customer_id=organisation.id,
            pbt_schedule_id=schedule.id,
            billing_rate=100,
        )
        rule = PBTScheduleRule(
            pbt_schedule_id=schedule.id,
            schedule_type="timesheet",
            frequency="fortnightly",
            anchor_date=date(2026, 1, 5),
            offset_days=1,
            active=True,
        )
        invoice_rule = PBTScheduleRule(
            pbt_schedule_id=schedule.id,
            schedule_type="invoice",
            frequency="monthly",
            offset_days=2,
            invoice_payment_terms_days=14,
            active=True,
        )
        db.add_all([assignment, rule, invoice_rule])
        db.flush()
        period = PBTSchedulePeriod(
            pbt_schedule_id=schedule.id,
            rule_id=rule.id,
            schedule_type="timesheet",
            period_start=date(2026, 1, 5),
            period_end=date(2026, 1, 18),
            event_date=date(2026, 1, 19),
            status="planned",
        )
        invoice_period = PBTSchedulePeriod(
            pbt_schedule_id=schedule.id,
            rule_id=invoice_rule.id,
            schedule_type="invoice",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            event_date=date(2026, 2, 2),
            payment_terms_days=14,
            customer_payment_due_date=date(2026, 2, 16),
            status="planned",
        )
        db.add_all([period, invoice_period])
        db.commit()
        return assignment.id, period.id, invoice_period.id


def test_timesheet_run_creates_complete_period_and_skips_duplicate():
    assignment_id, period_id, _ = _seed_expected_period()
    request = TimesheetRunCreate(selections=[TimesheetRunSelection(
        assignment_id=assignment_id,
        pbt_schedule_period_id=period_id,
    )])

    first = create_timesheet_run(request)
    second = create_timesheet_run(request)

    assert len(first["created"]) == 1
    assert first["skipped"] == []
    assert second["created"] == []
    assert len(second["skipped"]) == 1

    with SessionLocal() as db:
        header = db.scalar(select(TimesheetHeader).where(
            TimesheetHeader.assignment_id == assignment_id,
            TimesheetHeader.pbt_schedule_period_id == period_id,
        ))
        assert header.source == "pbt_schedule"
        assert header.period_type == "scheduled"
        assert db.scalar(select(func.count(Timesheet.id)).where(
            Timesheet.timesheet_header_id == header.id
        )) == 14


def test_approved_scheduled_timesheet_uses_pbt_invoice_dates():
    assignment_id, period_id, invoice_period_id = _seed_expected_period()
    result = create_timesheet_run(TimesheetRunCreate(selections=[
        TimesheetRunSelection(
            assignment_id=assignment_id,
            pbt_schedule_period_id=period_id,
        )
    ]))
    header_id = result["created"][0]["timesheet_header_id"]
    with SessionLocal() as db:
        entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.timesheet_header_id == header_id)
            .order_by(Timesheet.work_date)
        ).all()
        for entry in entries[:10]:
            entry.hours_worked = 8
        db.commit()

    approved = approve_scheduled_timesheet(header_id)
    assert approved["status"] == "approved"

    generated = create_invoice_from_timesheet(TimesheetInvoiceInput(
        period_type="scheduled",
        timesheet_id=header_id,
        engagement_id=assignment_id,
    ))
    with SessionLocal() as db:
        invoice = db.get(Invoice, generated["invoice_id"])
        assert invoice.issue_date == date(2026, 2, 2)
        assert invoice.due_date == date(2026, 2, 16)
        assert invoice.pbt_schedule_period_id == invoice_period_id
