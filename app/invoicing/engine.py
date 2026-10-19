from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.assignment import Assignment
from app.models.timesheet import Timesheet
from app.models.invoice import Invoice
from app.models.invoice_timesheet import InvoiceTimesheet
from app.invoicing.calculations import calculate_invoice



def generate_invoice(engagement_id: int, start_date: date, end_date: date):

    if start_date > end_date:
        raise ValueError("Start date cannot be after end date")

    with SessionLocal() as session:

        assignment = session.get(Assignment, engagement_id)

        if assignment is None:
            raise ValueError("Assignment not found")

        if assignment.engagement_id is None:
            raise ValueError("Assignment has no Engagement")

        # Retrieve approved timesheets that have not been invoiced
        timesheets = session.scalars(
            select(Timesheet).where(
                Timesheet.assignment_id == assignment.id,
                Timesheet.engagement_id == assignment.engagement_id,
                Timesheet.status == "approved",
                Timesheet.work_date >= start_date,
                Timesheet.work_date <= end_date,
                ~Timesheet.id.in_(
                    select(InvoiceTimesheet.timesheet_id)
                ),
            ).order_by(Timesheet.work_date)
        ).all()

        if not timesheets:
            raise ValueError("No approved, uninvoiced timesheets found")

        # Calculate total approved hours
        total_hours = sum(
            (t.hours_worked for t in timesheets),
            Decimal("0")
        )

        # Calculate invoice amounts
        amounts = calculate_invoice(
            total_hours,
            assignment.billing_rate
        )

        # Create invoice
        invoice = Invoice(
            engagement_id=assignment.id,
            invoice_number=(
                f"INV-{date.today():%Y%m%d}-"
                f"{assignment.id}-{timesheets[0].id}"
            ),
            issue_date=date.today(),
            subtotal=amounts["subtotal"],
            gst=amounts["gst"],
            total=amounts["total"],
            status="draft",
        )

        try:
            session.add(invoice)
            session.flush()

            # Link timesheets to invoice
            for timesheet in timesheets:
                session.add(
                    InvoiceTimesheet(
                        invoice_id=invoice.id,
                        timesheet_id=timesheet.id,
                    )
                )

            session.commit()

        except IntegrityError as error:
            session.rollback()
            raise ValueError(
                "Invoice creation failed. A timesheet may already be invoiced "
                "or the invoice number may already exist."
            ) from error

        invoice_id = invoice.id
        invoice_number = invoice.invoice_number

        return {
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            **amounts,
        }


def generate_invoice_for_timesheet(
    engagement_id: int,
    timesheet_ids: list[int],
):
    """Generate one invoice from explicitly selected timesheet entries."""

    if not timesheet_ids or len(timesheet_ids) != len(set(timesheet_ids)):
        raise ValueError("Invalid timesheet selection")

    with SessionLocal() as session:
        assignment = session.get(Assignment, engagement_id)

        if assignment is None:
            raise ValueError("Assignment not found")

        if assignment.engagement_id is None:
            raise ValueError("Assignment has no Engagement")

        timesheets = session.scalars(
            select(Timesheet)
            .where(Timesheet.id.in_(timesheet_ids))
            .order_by(Timesheet.work_date, Timesheet.id)
        ).all()

        if len(timesheets) != len(timesheet_ids):
            raise ValueError("One or more timesheets were not found")

        if any(
            t.assignment_id != assignment.id
            or t.engagement_id != assignment.engagement_id
            for t in timesheets
        ):
            raise ValueError("Timesheet does not match assignment and engagement")

        if any(t.status != "approved" for t in timesheets):
            raise ValueError("Only approved timesheets can be invoiced")

        existing = session.scalar(
            select(InvoiceTimesheet.timesheet_id)
            .where(InvoiceTimesheet.timesheet_id.in_(timesheet_ids))
            .limit(1)
        )

        if existing is not None:
            raise ValueError("One or more timesheets have already been invoiced")

        total_hours = sum(
            (t.hours_worked for t in timesheets),
            Decimal("0")
        )

        if total_hours <= 0:
            raise ValueError("Cannot invoice a timesheet with zero hours")

        amounts = calculate_invoice(
            total_hours,
            assignment.billing_rate
        )

        # Unique invoice number, independent of date or timesheet IDs.
        from uuid import uuid4

        invoice = Invoice(
            engagement_id=assignment.id,
            invoice_number=f"INV-{uuid4().hex[:12].upper()}",
            issue_date=date.today(),
            subtotal=amounts["subtotal"],
            gst=amounts["gst"],
            total=amounts["total"],
            status="draft",
        )

        try:
            session.add(invoice)
            session.flush()

            for timesheet in timesheets:
                session.add(
                    InvoiceTimesheet(
                        invoice_id=invoice.id,
                        timesheet_id=timesheet.id,
                    )
                )

            session.commit()
            invoice_id = invoice.id
            invoice_number = invoice.invoice_number

        except IntegrityError as error:
            session.rollback()
            raise ValueError(
                "Invoice creation failed. A timesheet may already be invoiced."
            ) from error

        return {
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            **amounts,
        }
