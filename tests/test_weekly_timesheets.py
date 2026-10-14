import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.database import SessionLocal
from app.main import (
    WeeklyTimesheetCreate,
    WeeklyTimesheetEntry,
    create_weekly_timesheet,
    update_weekly_timesheet,
    approve_weekly_timesheet,
)
from app.models.employee import Employee
from app.models.organisation import Organisation
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader


def unique_test_abn():
    return str(uuid.uuid4().int % 100_000_000_000).zfill(11)


def create_test_employee():
    """Create a test organisation and employee."""

    with SessionLocal() as db:

        organisation = Organisation(
            name=f"Weekly Timesheet Test {uuid.uuid4().hex[:8]}",
            abn=unique_test_abn(),
            country="AU",
        )

        db.add(organisation)
        db.flush()

        employee = Employee(
            organisation_id=organisation.id,
            first_name="Weekly",
            last_name="Tester",
            email=f"weekly-{uuid.uuid4().hex}@example.com",
        )

        db.add(employee)
        db.commit()

        return employee.id, organisation.id


def cleanup_test_data(employee_id, organisation_id, header_id=None):
    """Remove test timesheets, employee and organisation."""

    with SessionLocal() as db:

        daily_entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.employee_id == employee_id)
        ).all()

        for entry in daily_entries:
            db.delete(entry)

        db.flush()

        if header_id is not None:

            header = db.get(TimesheetHeader, header_id)

            if header is not None:
                db.delete(header)

        employee = db.get(Employee, employee_id)

        if employee is not None:
            db.delete(employee)

        organisation = db.get(Organisation, organisation_id)

        if organisation is not None:
            db.delete(organisation)

        db.commit()


def build_weekly_request(employee_id, week_start, friday_hours="8.00"):
    """Build a Monday-to-Sunday weekly timesheet request."""

    entries = [
        WeeklyTimesheetEntry(
            work_date=week_start + timedelta(days=i),
            hours_worked=(
                Decimal(friday_hours)
                if i == 4
                else Decimal("8.00")
                if i < 5
                else Decimal("0.00")
            ),
        )
        for i in range(7)
    ]

    return WeeklyTimesheetCreate(
        employee_id=employee_id,
        week_start=week_start,
        entries=entries,
    )


# ============================================================
# TEST 1: CREATE WEEKLY TIMESHEET
# ============================================================

def test_create_weekly_timesheet():

    week_start = date(2026, 10, 12)

    employee_id, organisation_id = create_test_employee()

    header_id = None

    try:

        request = build_weekly_request(
            employee_id,
            week_start,
        )

        # Create weekly timesheet
        result = create_weekly_timesheet(request)

        header_id = result["timesheet_header_id"]

        assert result["days_created"] == 7
        assert result["total_hours"] == Decimal("40.00")
        assert result["employee_id"] == employee_id

        # Verify database records
        with SessionLocal() as db:

            header = db.get(TimesheetHeader, header_id)

            assert header is not None
            assert header.employee_id == employee_id
            assert header.period_type == "weekly"
            assert header.period_start == week_start
            assert header.period_end == week_start + timedelta(days=6)
            assert header.status == "draft"

            daily_entries = db.scalars(
                select(Timesheet)
                .where(Timesheet.timesheet_header_id == header_id)
                .order_by(Timesheet.work_date)
            ).all()

            assert len(daily_entries) == 7

            assert all(
                entry.timesheet_header_id == header_id
                for entry in daily_entries
            )

            assert all(
                entry.status == "draft"
                for entry in daily_entries
            )

            assert sum(
                entry.hours_worked for entry in daily_entries
            ) == Decimal("40.00")

            assert [
                entry.work_date for entry in daily_entries
            ] == [
                week_start + timedelta(days=i)
                for i in range(7)
            ]

        # Duplicate submission must be rejected
        with pytest.raises(HTTPException) as error:
            create_weekly_timesheet(request)

        assert error.value.status_code == 409

    finally:

        cleanup_test_data(
            employee_id,
            organisation_id,
            header_id,
        )


# ============================================================
# TEST 2: EDIT, APPROVE AND LOCK WEEKLY TIMESHEET
# ============================================================

def test_weekly_timesheet_edit_and_approve():

    week_start = date(2026, 10, 26)

    employee_id, organisation_id = create_test_employee()

    header_id = None

    try:

        # ----------------------------------------------------
        # STEP 1: CREATE
        # ----------------------------------------------------

        request = build_weekly_request(
            employee_id,
            week_start,
        )

        created = create_weekly_timesheet(request)

        header_id = created["timesheet_header_id"]

        assert created["days_created"] == 7
        assert created["total_hours"] == Decimal("40.00")

        # ----------------------------------------------------
        # STEP 2: EDIT
        # ----------------------------------------------------

        # Change Friday from 8 hours to 6 hours.
        update_request = build_weekly_request(
            employee_id,
            week_start,
            friday_hours="6.00",
        )

        updated = update_weekly_timesheet(
            header_id,
            update_request,
        )

        assert updated["days_updated"] == 7
        assert updated["total_hours"] == Decimal("38.00")
        assert updated["status"] == "draft"

        # Verify updated hours in database
        with SessionLocal() as db:

            daily_entries = db.scalars(
                select(Timesheet)
                .where(Timesheet.timesheet_header_id == header_id)
                .order_by(Timesheet.work_date)
            ).all()

            assert len(daily_entries) == 7

            assert daily_entries[4].hours_worked == Decimal("6.00")

            assert sum(
                entry.hours_worked for entry in daily_entries
            ) == Decimal("38.00")

        # ----------------------------------------------------
        # STEP 3: APPROVE
        # ----------------------------------------------------

        approved = approve_weekly_timesheet(header_id)

        assert approved["status"] == "approved"
        assert approved["days_approved"] == 7
        assert approved["total_hours"] == Decimal("38.00")

        # ----------------------------------------------------
        # STEP 4: VERIFY DATABASE APPROVAL
        # ----------------------------------------------------

        with SessionLocal() as db:

            header = db.get(TimesheetHeader, header_id)

            assert header is not None
            assert header.status == "approved"

            daily_entries = db.scalars(
                select(Timesheet)
                .where(Timesheet.timesheet_header_id == header_id)
                .order_by(Timesheet.work_date)
            ).all()

            assert len(daily_entries) == 7

            assert all(
                entry.status == "approved"
                for entry in daily_entries
            )

            assert sum(
                entry.hours_worked for entry in daily_entries
            ) == Decimal("38.00")

        # ----------------------------------------------------
        # STEP 5: APPROVED TIMESHEET CANNOT BE EDITED
        # ----------------------------------------------------

        with pytest.raises(HTTPException) as error:

            update_weekly_timesheet(
                header_id,
                update_request,
            )

        assert error.value.status_code == 409

        # ----------------------------------------------------
        # STEP 6: APPROVED TIMESHEET CANNOT BE APPROVED AGAIN
        # ----------------------------------------------------

        with pytest.raises(HTTPException) as error:

            approve_weekly_timesheet(header_id)

        assert error.value.status_code == 409

    finally:

        cleanup_test_data(
            employee_id,
            organisation_id,
            header_id,
        )