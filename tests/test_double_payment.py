from datetime import date
from decimal import Decimal

from sqlalchemy import select

from test_authentication import client, login
from app.database import SessionLocal
from app.models.organisation import Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.timesheet import Timesheet
from app.models.payslip_timesheet import PayslipTimesheet
from uuid import uuid4

def test_prevent_double_payment(client):
    login(client)

    # Retrieve the CSRF token from the authenticated session
    from html import unescape
    import re

    response = client.get("/ui/timesheets/new")
    assert response.status_code == 200

    match = re.search(
        r'"X-CSRF-Token":\s*"([^"]+)"',
        response.text
    )

    assert match is not None
    csrf_token = unescape(match.group(1))

    with SessionLocal() as db:

        # Create a test organisation
        organisation = Organisation(
            name="Double Payment Test Organisation",
            #abn="98765432109"
            abn=str(uuid4().int)[:11]
        )
        db.add(organisation)
        db.flush()

        # Canonical worker and employer engagement.
        worker = Worker(
            first_name="Payroll",
            last_name="Tester",
            email="double-payment-test@example.com",
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

        # Create an approved timesheet
        timesheet = Timesheet(
            employee_id=None,
            engagement_id=engagement.id,
            work_date=date(2026, 10, 14),
            hours_worked=Decimal("7.60"),
            status="approved"
        )
        db.add(timesheet)
        db.flush()

        timesheet_id = timesheet.id

        # Create two approved pay runs for the same period
        pay_runs = []

        for _ in range(2):
            pay_run = PayRun(
                organisation_id=organisation.id,
                period_start=date(2026, 10, 1),
                period_end=date(2026, 10, 14),
                payment_date=date(2026, 10, 15),
                status="approved"
            )
            db.add(pay_run)
            db.flush()

            payslip = Payslip(
                pay_run_id=pay_run.id,
                employee_id=None,
            engagement_id=engagement.id,
                gross_pay=Decimal("342.00"),
                payg_withholding=Decimal("50.00"),
                net_pay=Decimal("292.00"),
                superannuation=Decimal("41.04")
            )
            db.add(payslip)
            db.flush()

            db.add(
                PayslipTimesheet(
                    payslip_id=payslip.id,
                    timesheet_id=timesheet_id
                )
            )

            pay_runs.append(pay_run.id)

        db.commit()
    
        
    # Complete the first pay run
    response = client.post(
        f"/pay-runs/{pay_runs[0]}/complete",
        headers={"X-CSRF-Token": csrf_token}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    # Attempt to complete the second pay run
    response = client.post(
        f"/pay-runs/{pay_runs[1]}/complete",
        headers={"X-CSRF-Token": csrf_token}
    )

    assert response.status_code == 400
    assert "timesheets already paid" in response.json()["detail"]

    # Verify the second pay run remains approved
    with SessionLocal() as db:
        second_pay_run = db.get(PayRun, pay_runs[1])
        assert second_pay_run.status == "approved"