from datetime import date
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.assignment import Assignment
from app.models.timesheet import Timesheet
from app.models.invoice import Invoice
from app.models.invoice_timesheet import InvoiceTimesheet
from app.models.assignment_component import AssignmentComponent
from app.models.component_definition import ComponentDefinition
from app.models.component_family import ComponentFamily
from app.models.invoice_component import InvoiceComponent


def _exclude_leave_timesheets(session, timesheets):
    """Customer invoices never include leave-family timesheet lines."""
    leave_definition_ids = set(session.scalars(
        select(ComponentDefinition.id)
        .join(
            ComponentFamily,
            ComponentFamily.id == ComponentDefinition.family_id,
        )
        .where(ComponentFamily.code == "LEAVE")
    ).all())
    return [
        row for row in timesheets
        if row.component_definition_id not in leave_definition_ids
    ]


def _invoice_lines(session, assignment, timesheets):
    """Calculate effective-dated ordinary and percentage invoice lines."""
    definitions = {
        definition.id: definition
        for definition in session.scalars(
            select(ComponentDefinition)
        ).all()
    }
    ordinary_definition = next(
        (
            definition for definition in definitions.values()
            if definition.code == "ORDINARY_HOURS"
        ),
        None,
    )
    configured = session.scalars(
        select(AssignmentComponent).where(
            AssignmentComponent.assignment_id == assignment.id,
            AssignmentComponent.applies_to.in_(("invoice", "both")),
        )
    ).all()

    has_percentage_component = any(
        definitions.get(component.component_definition_id) is not None
        and definitions[component.component_definition_id].calculation_type
        == "percentage"
        for component in configured
    )
    if has_percentage_component and ordinary_definition is None:
        raise ValueError(
            "ORDINARY_HOURS component definition is required for "
            "percentage invoice components"
        )

    component_amounts = defaultdict(
        lambda: {"quantity": Decimal("0"), "amount": Decimal("0")}
    )
    percentage_amounts = defaultdict(
        lambda: {"quantity": Decimal("0"), "amount": Decimal("0")}
    )

    for timesheet in timesheets:
        active = [
            component for component in configured
            if component.effective_from <= timesheet.work_date
            and (
                component.effective_to is None
                or component.effective_to >= timesheet.work_date
            )
        ]
        definition = (
            definitions.get(timesheet.component_definition_id)
            if timesheet.component_definition_id is not None
            else ordinary_definition
        )
        if definition is None and timesheet.component_definition_id is not None:
            raise ValueError("Timesheet component definition not found")
        if definition is not None and definition.code == "GST":
            raise ValueError("GST cannot be used as a Timesheet component")

        matching_components = [
            component for component in active
            if definition is not None
            and component.component_definition_id == definition.id
        ]

        if len(matching_components) > 1:
            raise ValueError(
                f"Multiple {definition.name if definition else 'ordinary'} "
                f"invoice rates apply on "
                f"{timesheet.work_date}"
            )

        if timesheet.component_definition_id is None:
            rate = (
                matching_components[0].bill_rate
                if matching_components else assignment.billing_rate
            )
        else:
            if not matching_components:
                raise ValueError(
                    f"{definition.name} is not configured for invoicing "
                    f"on {timesheet.work_date}"
                )
            rate = matching_components[0].bill_rate

        if rate is None or rate < 0:
            raise ValueError(
                f"Missing or invalid bill rate for "
                f"{definition.name if definition else 'ordinary services'} "
                f"on {timesheet.work_date}"
            )

        quantity = Decimal(timesheet.hours_worked)
        amount = (quantity * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        key = (definition.id if definition else None, rate)
        component_amounts[key]["quantity"] += quantity
        component_amounts[key]["amount"] += amount

        percentage_base = (
            amount if definition is None or definition.code == "ORDINARY_HOURS"
            else Decimal("0.00")
        )

        for component in active:
            percentage_definition = definitions.get(
                component.component_definition_id
            )
            if (
                percentage_definition is None
                or percentage_definition.calculation_type != "percentage"
                or percentage_definition.code == "GST"
                or (
                    definition is not None
                    and percentage_definition.id == definition.id
                )
                or component.bill_rate is None
            ):
                continue

            percentage_amount = (
                percentage_base * component.bill_rate / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            key = (percentage_definition.id, component.bill_rate)
            percentage_amounts[key]["quantity"] += percentage_base
            percentage_amounts[key]["amount"] += percentage_amount

    lines = []
    for (definition_id, rate), values in component_amounts.items():
        lines.append({
            "component_definition_id": definition_id,
            "description": (
                definitions[definition_id].name
                if definition_id is not None else "Services provided"
            ),
            "calculation_type": "hourly",
            "quantity": values["quantity"],
            "rate": rate,
            "amount": values["amount"],
        })

    for (definition_id, rate), values in percentage_amounts.items():
        lines.append({
            "component_definition_id": definition_id,
            "description": definitions[definition_id].name,
            "calculation_type": "percentage",
            "quantity": values["quantity"],
            "rate": rate,
            "amount": values["amount"],
        })

    return lines


def _invoice_amounts(lines, total_hours, fallback_rate):
    subtotal = sum(
        (line["amount"] for line in lines), Decimal("0.00")
    )
    gst = (subtotal * Decimal("0.10")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return {
        "hours": total_hours,
        "hourly_rate": fallback_rate,
        "subtotal": subtotal,
        "gst": gst,
        "total": subtotal + gst,
    }


def _save_invoice_lines(session, invoice, lines):
    for line in lines:
        if line["component_definition_id"] is None:
            continue
        session.add(InvoiceComponent(
            invoice_id=invoice.id,
            component_definition_id=line["component_definition_id"],
            quantity=line["quantity"],
            rate=line["rate"],
            amount=line["amount"],
        ))


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

        timesheets = _exclude_leave_timesheets(session, timesheets)
        if not timesheets:
            raise ValueError("No billable timesheet lines found")

        # Calculate total approved hours
        total_hours = sum(
            (t.hours_worked for t in timesheets),
            Decimal("0")
        )

        lines = _invoice_lines(session, assignment, timesheets)
        amounts = _invoice_amounts(
            lines, total_hours, assignment.billing_rate
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
            _save_invoice_lines(session, invoice, lines)

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
    issue_date: date | None = None,
    due_date: date | None = None,
    pbt_schedule_period_id: int | None = None,
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

        timesheets = _exclude_leave_timesheets(session, timesheets)
        if not timesheets:
            raise ValueError("No billable timesheet lines found")

        billable_ids = [timesheet.id for timesheet in timesheets]
        existing = session.scalar(
            select(InvoiceTimesheet.timesheet_id)
            .where(InvoiceTimesheet.timesheet_id.in_(billable_ids))
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

        lines = _invoice_lines(session, assignment, timesheets)
        amounts = _invoice_amounts(
            lines, total_hours, assignment.billing_rate
        )

        # Unique invoice number, independent of date or timesheet IDs.
        from uuid import uuid4

        invoice = Invoice(
            engagement_id=assignment.id,
            invoice_number=f"INV-{uuid4().hex[:12].upper()}",
            issue_date=issue_date or date.today(),
            due_date=due_date,
            pbt_schedule_period_id=pbt_schedule_period_id,
            subtotal=amounts["subtotal"],
            gst=amounts["gst"],
            total=amounts["total"],
            status="draft",
        )

        try:
            session.add(invoice)
            session.flush()
            _save_invoice_lines(session, invoice, lines)

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
