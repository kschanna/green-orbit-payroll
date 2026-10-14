from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from test_authentication import client, login
from app.database import SessionLocal
from app.models.employee import Employee
from app.models.timesheet import Timesheet
from app.models.organisation import Organisation
import uuid

def unique_test_abn():
    return str(uuid.uuid4().int % 100_000_000_000).zfill(11)


def test_create_timesheet(client):
    login(client)

    with SessionLocal() as db:
        organisation = Organisation(name="Timesheet Test Organisation",abn=unique_test_abn())
        db.add(organisation)
        db.flush()

        employee = Employee(
            organisation_id=organisation.id,
            first_name="Test",
            last_name="Employee",
            email="timesheet-test@example.com"
        )
        db.add(employee)
        db.commit()

        employee_id = employee.id
        organisation_id = organisation.id

    response = client.get("/ui/timesheets/new")
    assert response.status_code == 200

    from html import unescape
    import re

    match = re.search(r'"X-CSRF-Token":\s*"([^"]+)"', response.text)
    assert match is not None
    csrf_token = unescape(match.group(1))

    response = client.post(
        "/api/timesheets",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "employee_id": employee_id,
            "work_date": "2026-10-14",
            "hours_worked": 7.5,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    assert Decimal(response.json()["hours_worked"]) == Decimal("7.50")

    timesheet_id = response.json()["id"]

    with SessionLocal() as db:
        timesheet = db.get(Timesheet, timesheet_id)
        assert timesheet is not None
        assert timesheet.work_date == date(2026, 10, 14)
        db.delete(timesheet)
        db.commit()

        db.delete(db.get(Employee, employee_id))
        db.delete(db.get(Organisation, organisation_id))
        db.commit()

def test_edit_timesheet(client):
    login(client)

    with SessionLocal() as db:
        organisation = Organisation(
            name="Edit Test Organisation",
            abn=unique_test_abn()
        )
        db.add(organisation)
        db.flush()

        employee = Employee(
            organisation_id=organisation.id,
            first_name="Edit",
            last_name="Tester",
            email="edit-test@example.com"
        )
        db.add(employee)
        db.flush()

        timesheet = Timesheet(
            employee_id=employee.id,
            work_date=date(2026, 10, 14),
            hours_worked=Decimal("7.50"),
            status="draft"
        )
        db.add(timesheet)
        db.commit()

        timesheet_id = timesheet.id
        employee_id = employee.id
        organisation_id = organisation.id

    # Retrieve CSRF token from the edit page.
    response = client.get(f"/ui/timesheets/{timesheet_id}/edit")
    assert response.status_code == 200

    from html import unescape
    import re

    match = re.search(r'"X-CSRF-Token":\s*"([^"]+)"', response.text)
    assert match is not None
    csrf_token = unescape(match.group(1))

    # Update hours from 7.5 to 8.
    response = client.patch(
        f"/api/timesheets/{timesheet_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "employee_id": employee_id,
            "work_date": "2026-10-14",
            "hours_worked": 8
        }
    )

    assert response.status_code == 200

    with SessionLocal() as db:
        timesheet = db.get(Timesheet, timesheet_id)
        assert timesheet.hours_worked == Decimal("8.00")

        db.delete(timesheet)
        db.flush()
        db.delete(db.get(Employee, employee_id))
        db.flush()
        db.delete(db.get(Organisation, organisation_id))
        db.commit()

def test_approve_timesheet(client):
    login(client)

    with SessionLocal() as db:
        organisation = Organisation(
            name="Approval Test Organisation",
            abn=unique_test_abn()
        )
        db.add(organisation)
        db.flush()

        employee = Employee(
            organisation_id=organisation.id,
            first_name="Approval",
            last_name="Tester",
            email="approval-test@example.com"
        )
        db.add(employee)
        db.flush()

        timesheet = Timesheet(
            employee_id=employee.id,
            work_date=date(2026, 10, 14),
            hours_worked=Decimal("7.50"),
            status="draft"
        )
        db.add(timesheet)
        db.commit()

        timesheet_id = timesheet.id
        employee_id = employee.id
        organisation_id = organisation.id

    # Retrieve CSRF token from the timesheet list.
    response = client.get("/ui/timesheets")
    assert response.status_code == 200

    import re
    from html import unescape

    match = re.search(r'"X-CSRF-Token":\s*"([^"]+)"', response.text)
    assert match is not None
    csrf_token = unescape(match.group(1))

    # Approve the timesheet.
    response = client.post(
        f"/api/timesheets/{timesheet_id}/approve",
        headers={"X-CSRF-Token": csrf_token}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    # Verify approved timesheets cannot be edited.
    response = client.patch(
        f"/api/timesheets/{timesheet_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "employee_id": employee_id,
            "work_date": "2026-10-14",
            "hours_worked": 8
        }
    )

    assert response.status_code == 409

    # Clean up.
    with SessionLocal() as db:
        db.delete(db.get(Timesheet, timesheet_id))
        db.flush()
        db.delete(db.get(Employee, employee_id))
        db.flush()
        db.delete(db.get(Organisation, organisation_id))
        db.commit()