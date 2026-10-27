from datetime import date
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import delete, or_, select
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
from app.models.assignment_component_application import AssignmentComponentApplication
from app.models.invoice_component_allocation import InvoiceComponentAllocation


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


def _legacy_invoice_lines(session, assignment, timesheets):
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


STAGE_RANK = {"earnings": 100, "fee": 200, "on_cost": 300}
DERIVED_METHODS = {
    "percentage_of_value", "amount_per_unit",
    "fixed_per_invoice", "fixed_per_period",
}


def _invoice_lines(session, assignment, timesheets):
    """Realise ordered, effective-dated assignment invoice components."""
    definitions = {
        definition.id: definition
        for definition in session.scalars(select(ComponentDefinition)).all()
    }
    families = {
        family.id: family
        for family in session.scalars(select(ComponentFamily)).all()
    }
    ordinary = next((d for d in definitions.values() if d.code == "ORDINARY_HOURS"), None)
    configured = list(session.scalars(select(AssignmentComponent).where(
        AssignmentComponent.assignment_id == assignment.id,
        AssignmentComponent.applies_to.in_(("invoice", "both")),
    )).all())
    legacy_derived_ids = set()
    for component in configured:
        definition = definitions.get(component.component_definition_id)
        if (
            definition is not None
            and definition.calculation_type == "percentage"
            and component.calculation_method == "timesheet_rate"
        ):
            component.processing_stage = "fee"
            component.processing_order = 200
            component.calculation_method = "percentage_of_value"
            legacy_derived_ids.add(component.id)
    configured_by_id = {component.id: component for component in configured}
    applications = list(session.scalars(select(AssignmentComponentApplication).where(
        AssignmentComponentApplication.assignment_component_id.in_(configured_by_id)
    )).all()) if configured_by_id else []
    sources_by_target = defaultdict(list)
    for application in applications:
        target = configured_by_id.get(application.assignment_component_id)
        source = configured_by_id.get(application.source_assignment_component_id)
        if target is None or source is None:
            raise ValueError("Component application references another assignment")
        target_rank = (STAGE_RANK.get(target.processing_stage, 999), target.processing_order)
        source_rank = (STAGE_RANK.get(source.processing_stage, 999), source.processing_order)
        if target.id == source.id or source_rank >= target_rank:
            raise ValueError("Invoice component dependencies must point to an earlier component")
        sources_by_target[target.id].append(application)

    daily = defaultdict(list)
    for row in timesheets:
        definition = definitions.get(row.component_definition_id) if row.component_definition_id else ordinary
        if definition is not None and families.get(definition.family_id) and families[definition.family_id].code == "LEAVE":
            continue
        matches = [component for component in configured if (
            definition is not None
            and component.component_definition_id == definition.id
            and component.processing_stage == "earnings"
            and component.effective_from <= row.work_date
            and (component.effective_to is None or component.effective_to >= row.work_date)
        )]
        if len(matches) > 1:
            raise ValueError(f"Multiple {definition.name} invoice rates apply on {row.work_date}")
        component = matches[0] if matches else None
        if component is None and definition is not None and definition.code != "ORDINARY_HOURS":
            raise ValueError(f"{definition.name} is not configured for invoicing on {row.work_date}")
        rate = component.bill_rate if component else assignment.billing_rate
        if rate is None or rate < 0:
            raise ValueError(f"Missing or invalid bill rate for {definition.name if definition else 'ordinary services'} on {row.work_date}")
        quantity = Decimal(row.hours_worked)
        amount = (quantity * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        daily[row.work_date].append({
            "assignment_component_id": component.id if component else None,
            "component_definition_id": definition.id if definition else None,
            "component_code": definition.code if definition else "SERVICES",
            "component_name": definition.name if definition else "Services provided",
            "family_code": families[definition.family_id].code if definition else "EARNINGS",
            "calculation_method": "timesheet_rate",
            "calculation_type": "hourly",
            "unit_type": component.unit_type if component else "hours",
            "processing_order": component.processing_order if component else 100,
            "quantity": quantity, "rate": rate, "base_amount": amount,
            "amount": amount, "sources": [],
        })

    derived = sorted(
        (c for c in configured if c.processing_stage in {"fee", "on_cost"}),
        key=lambda c: (STAGE_RANK[c.processing_stage], c.processing_order, c.id),
    )
    invoice_dates = sorted(daily)
    for component in derived:
        if component.calculation_method not in DERIVED_METHODS:
            raise ValueError("Fee and on-cost components require a derived calculation method")
        definition = definitions[component.component_definition_id]
        family = families[definition.family_id]
        apps = sources_by_target[component.id]
        if (
            component.calculation_method in {"percentage_of_value", "amount_per_unit"}
            and not apps and component.id not in legacy_derived_ids
        ):
            raise ValueError(f"{definition.name} requires at least one source component")
        active_dates = [d for d in invoice_dates if component.effective_from <= d and (
            component.effective_to is None or component.effective_to >= d
        )]
        if not active_dates:
            continue
        dates = active_dates[:1] if component.calculation_method.startswith("fixed_per_") else active_dates
        for work_date in dates:
            source_rows = []
            for application in apps:
                source_rows.extend(
                    (entry, application)
                    for entry in daily[work_date]
                    if entry["assignment_component_id"] == application.source_assignment_component_id
                )
            if component.id in legacy_derived_ids and not apps:
                source_rows = [
                    (entry, type("LegacyApplication", (), {"basis": "value"})())
                    for entry in daily[work_date]
                    if entry["component_code"] in {"ORDINARY_HOURS", "SERVICES"}
                ]
            rate = component.bill_rate
            if rate is None or rate < 0:
                raise ValueError(f"Missing or invalid bill rate for {definition.name}")
            base_amount = sum((entry["amount"] for entry, _ in source_rows), Decimal("0"))
            source_units = sum((entry["quantity"] for entry, _ in source_rows), Decimal("0"))
            source_unit_types = {entry["unit_type"] for entry, _ in source_rows}
            if component.calculation_method == "percentage_of_value":
                quantity = base_amount
                amount = (base_amount * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                calc_type = "percentage"
            elif component.calculation_method == "amount_per_unit":
                quantity = source_units
                amount = (source_units * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                calc_type = "hourly"
            else:
                quantity = Decimal("1")
                base_amount = Decimal("0")
                amount = Decimal(rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                calc_type = "fixed"
            if not source_rows and component.calculation_method not in {"fixed_per_invoice", "fixed_per_period"}:
                continue
            daily[work_date].append({
                "assignment_component_id": component.id,
                "component_definition_id": definition.id,
                "component_code": definition.code,
                "component_name": definition.name,
                "family_code": family.code,
                "calculation_method": component.calculation_method,
                "calculation_type": calc_type,
                "unit_type": (
                    next(iter(source_unit_types))
                    if component.calculation_method == "amount_per_unit"
                    and len(source_unit_types) == 1
                    else component.unit_type
                ),
                "processing_order": component.processing_order,
                "quantity": quantity, "rate": rate, "base_amount": base_amount,
                "amount": amount,
                "sources": [{
                    "assignment_component_id": entry["assignment_component_id"],
                    "basis": application.basis,
                    "quantity": entry["quantity"], "amount": entry["amount"],
                } for entry, application in source_rows],
            })

    aggregated = {}
    for work_date in invoice_dates:
        for entry in daily[work_date]:
            key = (entry["assignment_component_id"], entry["component_definition_id"], entry["rate"], entry["calculation_method"])
            if key not in aggregated:
                aggregated[key] = dict(entry)
                aggregated[key]["sources"] = list(entry["sources"])
            else:
                result = aggregated[key]
                result["quantity"] += entry["quantity"]
                result["base_amount"] += entry["base_amount"]
                result["amount"] += entry["amount"]
                result["sources"].extend(entry["sources"])
    lines = sorted(aggregated.values(), key=lambda line: (line["processing_order"], line["component_name"]))
    for line in lines:
        if line["calculation_method"] == "percentage_of_value":
            line["explanation"] = f'{line["rate"]:.2f}% of ${line["base_amount"]:,.2f}'
        elif line["calculation_method"] == "amount_per_unit":
            line["explanation"] = f'{line["quantity"]:.4f} {line["unit_type"]} at ${line["rate"]}'
        elif line["calculation_method"].startswith("fixed_per_"):
            line["explanation"] = f'Fixed charge of ${line["rate"]}'
        else:
            line["explanation"] = f'{line["quantity"]:.4f} {line["unit_type"]} at ${line["rate"]}'
        line["description"] = line["component_name"]
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
    saved_by_assignment_component = {}
    saved = []
    for line in lines:
        row = InvoiceComponent(
            invoice_id=invoice.id,
            component_definition_id=line["component_definition_id"],
            assignment_component_id=line.get("assignment_component_id"),
            component_code=line.get("component_code"),
            component_name=line.get("component_name"),
            family_code=line.get("family_code"),
            calculation_method=line.get("calculation_method"),
            unit_type=line.get("unit_type"),
            base_amount=line.get("base_amount"),
            processing_order=line.get("processing_order"),
            explanation=line.get("explanation"),
            quantity=line["quantity"],
            rate=line["rate"],
            amount=line["amount"],
        )
        session.add(row)
        saved.append((row, line))
    session.flush()
    for row, line in saved:
        if line.get("assignment_component_id") is not None:
            saved_by_assignment_component[line["assignment_component_id"]] = row
    for row, line in saved:
        combined = defaultdict(lambda: {"quantity": Decimal("0"), "amount": Decimal("0"), "basis": "value"})
        for source in line.get("sources", []):
            source_id = source["assignment_component_id"]
            if source_id is None or source_id not in saved_by_assignment_component:
                continue
            combined[source_id]["quantity"] += source["quantity"]
            combined[source_id]["amount"] += source["amount"]
            combined[source_id]["basis"] = source["basis"]
        for source_id, values in combined.items():
            session.add(InvoiceComponentAllocation(
                invoice_component_id=row.id,
                source_invoice_component_id=saved_by_assignment_component[source_id].id,
                basis=values["basis"],
                source_quantity=values["quantity"],
                source_amount=values["amount"],
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


def delete_draft_invoice(invoice_id: int) -> None:
    """Delete a draft invoice and release its linked timesheets."""
    with SessionLocal() as session:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            raise LookupError("Invoice not found")
        if invoice.status != "draft":
            raise ValueError("Only draft invoices can be deleted")

        component_ids = list(session.scalars(
            select(InvoiceComponent.id).where(InvoiceComponent.invoice_id == invoice_id)
        ).all())
        if component_ids:
            session.execute(delete(InvoiceComponentAllocation).where(or_(
                InvoiceComponentAllocation.invoice_component_id.in_(component_ids),
                InvoiceComponentAllocation.source_invoice_component_id.in_(component_ids),
            )))
        session.execute(delete(InvoiceComponent).where(InvoiceComponent.invoice_id == invoice_id))
        session.execute(delete(InvoiceTimesheet).where(InvoiceTimesheet.invoice_id == invoice_id))
        session.delete(invoice)
        session.commit()
