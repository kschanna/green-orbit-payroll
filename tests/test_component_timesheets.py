from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import (
    WeeklyTimesheetCreate,
    WeeklyTimesheetEntry,
    create_weekly_timesheet,
    timesheet_component_options,
)
from app.invoicing.engine import generate_invoice_for_timesheet
from app.payroll.assignment_earnings import AssignmentEarningsCalculator
from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.assignment import Assignment
from app.models.component_family import ComponentFamily
from app.models.component_definition import ComponentDefinition
from app.models.assignment_component import AssignmentComponent
from app.models.timesheet import Timesheet
from app.models.invoice_component import InvoiceComponent
from app.models.invoice_timesheet import InvoiceTimesheet
from app.models.leave_plan import LeavePlan


@pytest.fixture
def component_data(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.main.SessionLocal", factory)
    monkeypatch.setattr("app.invoicing.engine.SessionLocal", factory)

    with Session(engine) as db:
        supplier = Organisation(name="Supplier", abn="11111111111")
        customer = Organisation(name="Customer", abn="22222222222")
        db.add_all([supplier, customer])
        db.flush()
        worker = Worker(first_name="Multi", last_name="Line", email="multi@example.com")
        db.add(worker)
        db.flush()
        engagement = Engagement(
            worker_id=worker.id,
            organisation_id=supplier.id,
            engagement_type="payg_contractor",
            status="active",
        )
        db.add(engagement)
        db.flush()
        assignment = Assignment(
            engagement_id=engagement.id,
            customer_id=customer.id,
            billing_rate=Decimal("100"),
        )
        db.add(assignment)
        db.flush()
        earnings = ComponentFamily(code="EARNINGS", name="Earnings")
        leave = ComponentFamily(code="LEAVE", name="Leave")
        other = ComponentFamily(code="FEE", name="Fee")
        db.add_all([earnings, leave, other])
        db.flush()
        ordinary = ComponentDefinition(
            family_id=earnings.id, code="ORDINARY_HOURS",
            name="Ordinary Hours", calculation_type="hourly", active=True,
        )
        overtime = ComponentDefinition(
            family_id=earnings.id, code="OVERTIME_150",
            name="Overtime 150%", calculation_type="hourly", active=True,
        )
        annual_leave = ComponentDefinition(
            family_id=leave.id, code="ANNUAL_LEAVE",
            name="Annual Leave", calculation_type="hourly", active=True,
        )
        fee = ComponentDefinition(
            family_id=other.id, code="ADMIN_FEE_TEST",
            name="Hidden Fee", calculation_type="percentage", active=True,
        )
        unconfigured = ComponentDefinition(
            family_id=earnings.id, code="UNCONFIGURED",
            name="Unconfigured", calculation_type="hourly", active=True,
        )
        db.add_all([ordinary, overtime, annual_leave, fee, unconfigured])
        db.flush()
        leave_plan = LeavePlan(
            worker_id=worker.id,
            engagement_id=engagement.id,
            component_definition_id=annual_leave.id,
            plan_basis="contractual",
            paid_leave_rate=Decimal("60"),
            annual_entitlement_hours=Decimal("152"),
            standard_hours_per_year=Decimal("1976"),
            accrual_rate_per_hour=Decimal("152") / Decimal("1976"),
            opening_balance_hours=Decimal("152"),
            allow_negative_balance=False,
            accrues_during_paid_leave=True,
            effective_from=date(2026, 10, 1),
            status="active",
        )
        db.add(leave_plan)
        for definition, pay, bill in (
            (ordinary, "50", "100"),
            (overtime, "75", "150"),
            (fee, None, "10"),
        ):
            db.add(AssignmentComponent(
                assignment_id=assignment.id,
                component_definition_id=definition.id,
                pay_rate=Decimal(pay) if pay else None,
                bill_rate=Decimal(bill),
                applies_to="both" if pay else "invoice",
                effective_from=date(2026, 10, 1),
            ))
        db.commit()
        ids = {
            "engagement": engagement.id,
            "assignment": assignment.id,
            "ordinary": ordinary.id,
            "overtime": overtime.id,
            "leave": annual_leave.id,
            "leave_plan": leave_plan.id,
            "fee": fee.id,
            "unconfigured": unconfigured.id,
        }
    yield engine, ids
    engine.dispose()


def weekly_payload(ids, extra_hours=Decimal("2")):
    monday = date(2026, 10, 12)
    entries = [
        WeeklyTimesheetEntry(
            work_date=monday + timedelta(days=day),
            assignment_id=ids["assignment"],
            component_definition_id=ids["ordinary"],
            hours_worked=Decimal("8") if day < 5 else Decimal("0"),
        )
        for day in range(7)
    ]
    entries.append(WeeklyTimesheetEntry(
        work_date=monday + timedelta(days=1),
        assignment_id=ids["assignment"],
        component_definition_id=ids["overtime"],
        hours_worked=extra_hours,
    ))
    return WeeklyTimesheetCreate(
        engagement_id=ids["engagement"], week_start=monday, entries=entries,
    )


def test_weekly_timesheet_supports_multiple_component_lines(component_data):
    engine, ids = component_data
    result = create_weekly_timesheet(weekly_payload(ids))
    assert result["lines_created"] == 8
    assert result["days_created"] == 7
    assert result["total_hours"] == Decimal("42")
    with Session(engine) as db:
        rows = db.scalars(
            select(Timesheet).where(
                Timesheet.timesheet_header_id == result["timesheet_header_id"]
            )
        ).all()
        assert len(rows) == 8
        assert sum(row.work_date == date(2026, 10, 13) for row in rows) == 2


def test_component_options_are_configured_earnings_and_leave_only(component_data):
    engine, ids = component_data
    with Session(engine) as db:
        options = timesheet_component_options(
            db, ids["assignment"], date(2026, 10, 12)
        )
    assert {item["id"] for item in options} == {
        ids["ordinary"], ids["overtime"], ids["leave"]
    }
    assert {item["family_code"] for item in options} == {"EARNINGS", "LEAVE"}


def test_timesheet_editors_default_the_only_earning_component():
    for template_name in ("timesheet_weekly.html", "timesheet_scheduled_edit.html"):
        template = Path("app/templates", template_name).read_text()
        assert "family_code" in template
        assert "earningItems.length===1" in template


def test_weekly_rejects_unconfigured_component_and_over_24_hours(component_data):
    _, ids = component_data
    payload = weekly_payload(ids)
    payload.entries[0].component_definition_id = ids["unconfigured"]
    with pytest.raises(HTTPException, match="not active and configured"):
        create_weekly_timesheet(payload)

    payload = weekly_payload(ids, extra_hours=Decimal("17"))
    with pytest.raises(HTTPException, match="cannot exceed 24"):
        create_weekly_timesheet(payload)


def test_expired_component_is_not_available(component_data):
    engine, ids = component_data
    with Session(engine) as db:
        component = db.scalar(
            select(AssignmentComponent).where(
                AssignmentComponent.assignment_id == ids["assignment"],
                AssignmentComponent.component_definition_id == ids["overtime"],
            )
        )
        component.effective_to = date(2026, 10, 11)
        db.commit()
        options = timesheet_component_options(
            db, ids["assignment"], date(2026, 10, 12)
        )
    assert ids["overtime"] not in {item["id"] for item in options}


def test_missing_invoice_and_payroll_rates_are_rejected(component_data):
    engine, ids = component_data
    with Session(engine) as db:
        component = db.scalar(
            select(AssignmentComponent).where(
                AssignmentComponent.assignment_id == ids["assignment"],
                AssignmentComponent.component_definition_id == ids["overtime"],
            )
        )
        component.bill_rate = None
        component.pay_rate = None
        row = Timesheet(
            engagement_id=ids["engagement"], assignment_id=ids["assignment"],
            component_definition_id=ids["overtime"],
            work_date=date(2026, 10, 12), hours_worked=Decimal("2"),
            status="approved",
        )
        db.add(row)
        db.commit()
        row_id = row.id
        with pytest.raises(ValueError, match="Invalid pay rate"):
            AssignmentEarningsCalculator().calculate(
                db, db.get(Engagement, ids["engagement"]), [row]
            )

    with pytest.raises(ValueError, match="Missing or invalid bill rate"):
        generate_invoice_for_timesheet(ids["assignment"], [row_id])


def test_invoice_and_payroll_group_multiple_components(component_data):
    engine, ids = component_data
    with Session(engine) as db:
        rows = [
            Timesheet(
                engagement_id=ids["engagement"], assignment_id=ids["assignment"],
                component_definition_id=component_id,
                work_date=date(2026, 10, 12), hours_worked=hours,
                status="approved",
            )
            for component_id, hours in (
                (ids["ordinary"], Decimal("8")),
                (ids["overtime"], Decimal("2")),
            )
        ]
        db.add_all(rows)
        db.commit()
        row_ids = [row.id for row in rows]
        earnings = AssignmentEarningsCalculator().calculate(
            db, db.get(Engagement, ids["engagement"]), rows
        )
        assert earnings["gross_pay"] == Decimal("550.00")
        assert len(earnings["lines"]) == 2

    result = generate_invoice_for_timesheet(ids["assignment"], row_ids)
    assert result["subtotal"] == Decimal("1180.00")
    with Session(engine) as db:
        lines = db.scalars(
            select(InvoiceComponent).where(
                InvoiceComponent.invoice_id == result["invoice_id"]
            )
        ).all()
        assert sorted(line.amount for line in lines) == [
            Decimal("80.00"), Decimal("300.00"), Decimal("800.00")
        ]


def test_contractor_leave_payroll_uses_leave_plan_rate(component_data):
    engine, ids = component_data
    with Session(engine) as db:
        row = Timesheet(
            engagement_id=ids["engagement"], assignment_id=ids["assignment"],
            component_definition_id=ids["leave"],
            leave_plan_id=ids["leave_plan"],
            work_date=date(2026, 10, 12), hours_worked=Decimal("2"),
            status="approved",
        )
        db.add(row)
        db.flush()
        earnings = AssignmentEarningsCalculator().calculate(
            db, db.get(Engagement, ids["engagement"]), [row]
        )

    assert earnings["gross_pay"] == Decimal("120.00")
    assert earnings["lines"][0]["rate"] == Decimal("60")


def test_invoice_excludes_leave_component_rows(component_data):
    engine, ids = component_data
    with Session(engine) as db:
        ordinary = Timesheet(
            engagement_id=ids["engagement"], assignment_id=ids["assignment"],
            component_definition_id=ids["ordinary"],
            work_date=date(2026, 10, 12), hours_worked=Decimal("8"),
            status="approved",
        )
        leave = Timesheet(
            engagement_id=ids["engagement"], assignment_id=ids["assignment"],
            component_definition_id=ids["leave"],
            leave_plan_id=ids["leave_plan"],
            work_date=date(2026, 10, 13), hours_worked=Decimal("2"),
            status="approved",
        )
        db.add_all([ordinary, leave])
        db.commit()
        ordinary_id = ordinary.id
        leave_id = leave.id

    result = generate_invoice_for_timesheet(
        ids["assignment"], [ordinary_id, leave_id]
    )
    assert result["hours"] == Decimal("8")
    assert result["subtotal"] == Decimal("880.00")

    with Session(engine) as db:
        linked_ids = set(db.scalars(
            select(InvoiceTimesheet.timesheet_id).where(
                InvoiceTimesheet.invoice_id == result["invoice_id"]
            )
        ).all())
    assert linked_ids == {ordinary_id}


def test_leave_only_timesheet_cannot_raise_invoice(component_data):
    engine, ids = component_data
    with Session(engine) as db:
        leave = Timesheet(
            engagement_id=ids["engagement"], assignment_id=ids["assignment"],
            component_definition_id=ids["leave"],
            leave_plan_id=ids["leave_plan"],
            work_date=date(2026, 10, 13), hours_worked=Decimal("2"),
            status="approved",
        )
        db.add(leave)
        db.commit()
        leave_id = leave.id

    with pytest.raises(ValueError, match="No billable timesheet lines found"):
        generate_invoice_for_timesheet(ids["assignment"], [leave_id])
