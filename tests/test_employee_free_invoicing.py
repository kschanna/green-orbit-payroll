
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.assignment import Assignment
from app.models.timesheet import Timesheet
from app.models.leave_plan import LeavePlan  # noqa: F401
from app.models.invoice import Invoice
from app.models.invoice_timesheet import InvoiceTimesheet
from app.models.invoice_component import InvoiceComponent
from app.models.component_family import ComponentFamily
from app.models.component_definition import ComponentDefinition
from app.models.assignment_component import AssignmentComponent
from app.models.assignment_component_application import AssignmentComponentApplication
from app.models.invoice_component_allocation import InvoiceComponentAllocation

from app.invoicing.engine import (
    delete_draft_invoice,
    generate_invoice,
    generate_invoice_for_timesheet,
)


def test_delete_draft_invoice_releases_timesheet(invoicing_data):
    engine, (assignment_id, _, timesheet_id) = invoicing_data
    result = generate_invoice_for_timesheet(assignment_id, [timesheet_id])

    delete_draft_invoice(result["invoice_id"])

    with Session(engine) as session:
        assert session.get(Invoice, result["invoice_id"]) is None
        assert session.scalar(select(func.count()).select_from(InvoiceTimesheet)) == 0
        assert session.scalar(select(func.count()).select_from(InvoiceComponent)) == 0
    replacement = generate_invoice_for_timesheet(assignment_id, [timesheet_id])
    with Session(engine) as session:
        assert session.get(Invoice, replacement["invoice_id"]) is not None
        assert session.scalar(select(func.count()).select_from(InvoiceTimesheet)) == 1


def test_delete_invoice_rejects_non_draft(invoicing_data):
    engine, (assignment_id, _, timesheet_id) = invoicing_data
    result = generate_invoice_for_timesheet(assignment_id, [timesheet_id])
    with Session(engine) as session:
        session.get(Invoice, result["invoice_id"]).status = "issued"
        session.commit()

    with pytest.raises(ValueError, match="Only draft invoices"):
        delete_draft_invoice(result["invoice_id"])


@pytest.fixture
def invoicing_data(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=engine)

    monkeypatch.setattr(
        "app.invoicing.engine.SessionLocal",
        factory,
    )

    with Session(engine) as session:
        supplier = Organisation(
            name="Test Supplier",
            abn="12345678901",
            country="AU",
        )
        customer = Organisation(
            name="Test Customer",
            abn="98765432109",
            country="AU",
        )
        session.add_all([supplier, customer])
        session.flush()

        worker = Worker(
            first_name="Sara",
            last_name="Ali",
            email="sara.invoice@example.com",
        )
        session.add(worker)
        session.flush()

        engagement = Engagement(
            worker_id=worker.id,
            organisation_id=supplier.id,
            engagement_type="employee",
            status="active",
        )
        session.add(engagement)
        session.flush()

        assignment = Assignment(
            engagement_id=engagement.id,
            employee_id=None,
            customer_id=customer.id,
            billing_rate=Decimal("150.00"),
        )
        session.add(assignment)
        session.flush()

        other_assignment = Assignment(
            engagement_id=engagement.id,
            employee_id=None,
            customer_id=customer.id,
            billing_rate=Decimal("175.00"),
        )
        session.add(other_assignment)
        session.flush()

        timesheet = Timesheet(
            engagement_id=engagement.id,
            employee_id=None,
            assignment_id=assignment.id,
            work_date=date(2026, 10, 14),
            hours_worked=Decimal("7.50"),
            status="approved",
        )
        session.add(timesheet)
        session.commit()

        data = (
            assignment.id,
            other_assignment.id,
            timesheet.id,
        )

    yield engine, data

    engine.dispose()


def test_employee_free_invoice_and_duplicate_prevention(invoicing_data):
    engine, (assignment_id, _, timesheet_id) = invoicing_data

    result = generate_invoice(
        engagement_id=assignment_id,
        start_date=date(2026, 10, 14),
        end_date=date(2026, 10, 14),
    )

    assert result["hours"] == Decimal("7.50")
    assert result["subtotal"] == Decimal("1125.00")
    assert result["gst"] == Decimal("112.50")
    assert result["total"] == Decimal("1237.50")

    with Session(engine) as session:
        assert session.scalar(
            select(func.count()).select_from(Worker)
        ) >= 1

        invoice = session.get(Invoice, result["invoice_id"])

        # Legacy column still stores the Assignment ID.
        assert invoice.engagement_id == assignment_id

        links = session.scalars(
            select(InvoiceTimesheet).where(
                InvoiceTimesheet.invoice_id == invoice.id
            )
        ).all()

        assert len(links) == 1
        assert links[0].timesheet_id == timesheet_id

    with pytest.raises(
        ValueError,
        match="No approved, uninvoiced timesheets found",
    ):
        generate_invoice(
            engagement_id=assignment_id,
            start_date=date(2026, 10, 14),
            end_date=date(2026, 10, 14),
        )


def test_cross_assignment_invoice_rejected(invoicing_data):
    _, (_, other_assignment_id, timesheet_id) = invoicing_data

    with pytest.raises(
        ValueError,
        match="Timesheet does not match assignment and engagement",
    ):
        generate_invoice_for_timesheet(
            engagement_id=other_assignment_id,
            timesheet_ids=[timesheet_id],
        )


def test_explicit_employee_free_invoice(invoicing_data):
    engine, (assignment_id, _, timesheet_id) = invoicing_data

    result = generate_invoice_for_timesheet(
        engagement_id=assignment_id,
        timesheet_ids=[timesheet_id],
    )

    assert result["subtotal"] == Decimal("1125.00")
    assert result["gst"] == Decimal("112.50")
    assert result["total"] == Decimal("1237.50")

    with Session(engine) as session:
        assert session.scalar(
            select(func.count()).select_from(Worker)
        ) >= 1


def test_invoice_uses_assignment_components_and_percentage_admin_fee(
    invoicing_data,
):
    engine, (assignment_id, _, _) = invoicing_data

    with Session(engine) as session:
        family = ComponentFamily(code="INVOICE", name="Invoice Charges")
        session.add(family)
        session.flush()
        ordinary = ComponentDefinition(
            family_id=family.id,
            code="ORDINARY_HOURS",
            name="Ordinary Services",
            calculation_type="hourly",
            active=True,
        )
        admin_fee = ComponentDefinition(
            family_id=family.id,
            code="ADMIN_FEE",
            name="Administration Fee",
            calculation_type="percentage",
            active=True,
        )
        session.add_all([ordinary, admin_fee])
        session.flush()
        session.add_all([
            AssignmentComponent(
                assignment_id=assignment_id,
                component_definition_id=ordinary.id,
                bill_rate=Decimal("160.00"),
                applies_to="invoice",
                effective_from=date(2026, 10, 1),
            ),
            AssignmentComponent(
                assignment_id=assignment_id,
                component_definition_id=admin_fee.id,
                bill_rate=Decimal("10.00"),
                applies_to="invoice",
                effective_from=date(2026, 10, 1),
            ),
        ])
        session.commit()

    result = generate_invoice(
        engagement_id=assignment_id,
        start_date=date(2026, 10, 14),
        end_date=date(2026, 10, 14),
    )

    assert result["subtotal"] == Decimal("1320.00")
    assert result["gst"] == Decimal("132.00")
    assert result["total"] == Decimal("1452.00")

    with Session(engine) as session:
        lines = session.scalars(
            select(InvoiceComponent)
            .where(InvoiceComponent.invoice_id == result["invoice_id"])
            .order_by(InvoiceComponent.id)
        ).all()

        assert len(lines) == 2
        assert lines[0].quantity == Decimal("7.5000")
        assert lines[0].rate == Decimal("160.0000")
        assert lines[0].amount == Decimal("1200.00")
        assert lines[1].quantity == Decimal("1200.0000")
        assert lines[1].rate == Decimal("10.0000")
        assert lines[1].amount == Decimal("120.00")


def test_invoice_processes_earnings_fees_and_on_cost_dependencies(invoicing_data):
    engine, (assignment_id, _, _) = invoicing_data
    with Session(engine) as session:
        families = {}
        for code, name in (("EARNINGS", "Earnings"), ("FEE", "Fees"), ("ON_COST", "On-cost")):
            family = ComponentFamily(code=code, name=name)
            session.add(family)
            session.flush()
            families[code] = family
        ordinary = ComponentDefinition(family_id=families["EARNINGS"].id, code="ORDINARY_HOURS", name="Ordinary", calculation_type="hourly", active=True)
        fee_def = ComponentDefinition(family_id=families["FEE"].id, code="ADMIN_FEE", name="Admin fee", calculation_type="percentage", active=True)
        cost_def = ComponentDefinition(family_id=families["ON_COST"].id, code="INSURANCE", name="Insurance", calculation_type="percentage", active=True)
        session.add_all([ordinary, fee_def, cost_def])
        session.flush()
        earning = AssignmentComponent(assignment_id=assignment_id, component_definition_id=ordinary.id, bill_rate=Decimal("160"), applies_to="invoice", processing_stage="earnings", processing_order=100, calculation_method="timesheet_rate", unit_type="hours", effective_from=date(2026, 10, 1))
        fee = AssignmentComponent(assignment_id=assignment_id, component_definition_id=fee_def.id, bill_rate=Decimal("10"), applies_to="invoice", processing_stage="fee", processing_order=200, calculation_method="percentage_of_value", unit_type="units", effective_from=date(2026, 10, 1))
        cost = AssignmentComponent(assignment_id=assignment_id, component_definition_id=cost_def.id, bill_rate=Decimal("5"), applies_to="invoice", processing_stage="on_cost", processing_order=300, calculation_method="percentage_of_value", unit_type="units", effective_from=date(2026, 10, 1))
        session.add_all([earning, fee, cost])
        session.flush()
        session.add_all([
            AssignmentComponentApplication(assignment_component_id=fee.id, source_assignment_component_id=earning.id, basis="value"),
            AssignmentComponentApplication(assignment_component_id=cost.id, source_assignment_component_id=earning.id, basis="value"),
            AssignmentComponentApplication(assignment_component_id=cost.id, source_assignment_component_id=fee.id, basis="value"),
        ])
        session.commit()

    result = generate_invoice(assignment_id, date(2026, 10, 14), date(2026, 10, 14))
    assert result["subtotal"] == Decimal("1386.00")
    with Session(engine) as session:
        lines = session.scalars(select(InvoiceComponent).where(InvoiceComponent.invoice_id == result["invoice_id"]).order_by(InvoiceComponent.processing_order)).all()
        assert [line.amount for line in lines] == [Decimal("1200.00"), Decimal("120.00"), Decimal("66.00")]
        assert session.scalar(select(func.count()).select_from(InvoiceComponentAllocation)) == 3
