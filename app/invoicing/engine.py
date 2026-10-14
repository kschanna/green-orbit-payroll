from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.worker_engagement import WorkerEngagement
from app.models.employee import Employee
from app.models.timesheet import Timesheet
from app.models.invoice import Invoice
from app.models.invoice_timesheet import InvoiceTimesheet
from app.invoicing.calculations import calculate_invoice



def generate_invoice(engagement_id: int, start_date: date, end_date: date):

    if start_date > end_date:
        raise ValueError("Start date cannot be after end date")

    with SessionLocal() as session:

        engagement = session.get(WorkerEngagement, engagement_id)

        if engagement is None:
            raise ValueError("Worker engagement not found")

        # Retrieve approved timesheets that have not been invoiced
        timesheets = session.scalars(
            select(Timesheet).where(
                Timesheet.employee_id == engagement.employee_id,
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
            engagement.billing_rate
        )

        # Create invoice
        invoice = Invoice(
            engagement_id=engagement.id,
            invoice_number=(
                f"INV-{date.today():%Y%m%d}-"
                f"{engagement.id}-{timesheets[0].id}"
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