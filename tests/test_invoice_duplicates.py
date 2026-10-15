from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.invoicing.engine import generate_invoice
from app.models.organisation import Organisation
from app.models.employee import Employee
from app.models.assignment import Assignment
from app.models.timesheet import Timesheet
from app.models.invoice import Invoice
from app.models.invoice_timesheet import InvoiceTimesheet


def test_duplicate_invoice_prevention():
    unique_id = uuid4().hex[:10]
    engagement_id = None

    with SessionLocal() as session:
        supplier = Organisation(
            name="Test Supplier",
            abn=f"1{unique_id[:10]}".replace(
                "a", "1"
            ).replace("b", "2").replace("c", "3")
             .replace("d", "4").replace("e", "5")
             .replace("f", "6"),
        )

        customer = Organisation(
            name="Test Customer",
            abn="2" + "".join(
                str(int(c, 16) % 10) for c in unique_id
            ),
        )

        session.add_all([supplier, customer])
        session.flush()

        employee = Employee(
            organisation_id=supplier.id,
            first_name="Test",
            last_name="Employee",
            email=f"invoice-test-{unique_id}@example.com",
        )
        session.add(employee)
        session.flush()

        engagement = Assignment(
            employee_id=employee.id,
            customer_id=customer.id,
            billing_rate=Decimal("150.00"),
        )
        session.add(engagement)
        session.flush()

        timesheet = Timesheet(
            employee_id=employee.id,
            work_date=date(2026, 10, 14),
            hours_worked=Decimal("7.50"),
            status="approved",
        )
        session.add(timesheet)
        session.commit()

        engagement_id = engagement.id
        employee_id = employee.id
        supplier_id = supplier.id
        customer_id = customer.id

    try:
        # First invoice should succeed
        result = generate_invoice(
            engagement_id=engagement_id,
            start_date=date(2026, 10, 14),
            end_date=date(2026, 10, 14),
        )

        assert result["invoice_id"] is not None

        # Second invoice must be rejected
        with pytest.raises(
            ValueError,
            match="No approved, uninvoiced timesheets found",
        ):
            generate_invoice(
                engagement_id=engagement_id,
                start_date=date(2026, 10, 14),
                end_date=date(2026, 10, 14),
            )

    finally:
        # Remove test records in foreign-key order
        with SessionLocal() as session:
            session.query(InvoiceTimesheet).filter(
                InvoiceTimesheet.invoice_id == result["invoice_id"]
            ).delete()

            session.query(Invoice).filter(
                Invoice.id == result["invoice_id"]
            ).delete()

            session.query(Timesheet).filter(
                Timesheet.employee_id == employee_id
            ).delete()

            session.query(Assignment).filter(
                Assignment.id == engagement_id
            ).delete()

            session.query(Employee).filter(
                Employee.id == employee_id
            ).delete()

            session.query(Organisation).filter(
                Organisation.id.in_([supplier_id, customer_id])
            ).delete(synchronize_session=False)

            session.commit()