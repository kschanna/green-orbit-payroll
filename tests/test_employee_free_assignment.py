
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.assignment import Assignment
from app.models.assignment_component import AssignmentComponent
from app.models.component_definition import ComponentDefinition
from app.models.component_family import ComponentFamily
from app.models.timesheet import Timesheet

from app.payroll.assignment_earnings import AssignmentEarningsCalculator


def test_assignment_earnings_without_employee():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        organisation = Organisation(
            name="Assignment Test Organisation",
            abn="12345678901",
            country="AU",
        )
        session.add(organisation)
        session.flush()

        worker = Worker(
            first_name="Sara",
            last_name="Ali",
            email="sara.assignment@example.com",
        )
        session.add(worker)
        session.flush()

        engagement = Engagement(
            worker_id=worker.id,
            organisation_id=organisation.id,
            engagement_type="employee",
            status="active",
        )
        session.add(engagement)
        session.flush()

        assignment = Assignment(
            engagement_id=engagement.id,
            employee_id=None,
            customer_id=organisation.id,
            billing_rate=Decimal("90.00"),
        )
        session.add(assignment)
        session.flush()

        family = ComponentFamily(
            code="EARNINGS",
            name="Earnings",
        )
        session.add(family)
        session.flush()

        definition = ComponentDefinition(
            family_id=family.id,
            code="ORDINARY_HOURS",
            name="Ordinary Hours",
            calculation_type="hourly",
        )
        session.add(definition)
        session.flush()

        component = AssignmentComponent(
            assignment_id=assignment.id,
            component_definition_id=definition.id,
            applies_to="payroll",
            pay_rate=Decimal("50.00"),
            effective_from=date(2026, 10, 1),
        )
        session.add(component)

        timesheet = Timesheet(
            engagement_id=engagement.id,
            employee_id=None,
            assignment_id=assignment.id,
            work_date=date(2026, 10, 5),
            hours_worked=Decimal("8.00"),
            status="approved",
        )
        session.add(timesheet)
        session.flush()

        assert session.scalar(
            select(func.count()).select_from(Worker)
        ) >= 1

        result = AssignmentEarningsCalculator().calculate(
            session=session,
            engagement=engagement,
            timesheets=[timesheet],
        )

        assert result["gross_pay"] == Decimal("400.00")
        assert len(result["lines"]) == 1
        assert result["lines"][0]["quantity"] == Decimal("8.00")
        assert result["lines"][0]["rate"] == Decimal("50.00")
        assert result["lines"][0]["amount"] == Decimal("400.00")

        assert session.scalar(
            select(func.count()).select_from(Worker)
        ) >= 1
