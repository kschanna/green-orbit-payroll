
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.assignment import Assignment
from app.models.assignment_component import AssignmentComponent
from app.models.component_family import ComponentFamily
from app.models.component_definition import ComponentDefinition
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.timesheet import Timesheet
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.payroll_component import PayrollComponent

from app.payroll.pay_run_processor import PayRunProcessor
from app.reports.payslip_pdf import PayslipPDFGenerator


@pytest.fixture
def payroll_data():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            employer = Organisation(
                name="Test Employer",
                abn="12345678901",
                country="AU",
            )
            customer = Organisation(
                name="Test Customer",
                abn="98765432109",
                country="AU",
            )
            session.add_all([employer, customer])
            session.flush()

            worker = Worker(
                first_name="Ahmed",
                last_name="Khan",
                email="ahmed@components.test",
            )
            session.add(worker)
            session.flush()
            engagement = Engagement(
                worker_id=worker.id,
                organisation_id=employer.id,
                engagement_type="employee",
                status="active",
            )
            session.add(engagement)
            session.flush()
            worker_id = worker.id

            families = {}
            for code, name in (
                ("EARNINGS", "Earnings"),
                ("TAX", "Tax"),
                ("SUPERANNUATION", "Superannuation"),
            ):
                family = ComponentFamily(code=code, name=name)
                session.add(family)
                session.flush()
                families[code] = family

            definitions = {}
            for code, name, family_code, calculation_type in (
                ("ORDINARY_HOURS", "Ordinary Hours", "EARNINGS", "hourly"),
                ("PAYG_WITHHOLDING", "PAYG Withholding", "TAX", "fixed"),
                ("SUPER_GUARANTEE", "Superannuation Guarantee",
                 "SUPERANNUATION", "percentage"),
                ("SUPER_EMPLOYER_EXTRA", "Additional Employer Superannuation",
                 "SUPERANNUATION", "fixed"),
            ):
                definition = ComponentDefinition(
                    family_id=families[family_code].id,
                    code=code,
                    name=name,
                    calculation_type=calculation_type,
                    active=True,
                )
                session.add(definition)
                session.flush()
                definitions[code] = definition

            assignment = Assignment(
                employee_id=None,
                engagement_id=engagement.id,
                customer_id=customer.id,
                billing_rate=Decimal("100.00"),
            )
            session.add(assignment)
            session.flush()

            session.add(
                AssignmentComponent(
                    assignment_id=assignment.id,
                    component_definition_id=definitions["ORDINARY_HOURS"].id,
                    pay_rate=Decimal("55.00"),
                    applies_to="payroll",
                    effective_from=date(2026, 10, 1),
                )
            )

            session.add(
                EmployeeTaxProfile(
                    worker_id=worker_id,
                    employee_id=None,
                    residency_status="resident",
                    claims_tax_free_threshold=True,
                    has_study_loan=False,
                    tfn_declaration_received=True,
                    effective_from=date(2026, 10, 1),
                )
            )

            session.add(
                EmployeeSuperProfile(
                    worker_id=worker_id,
                    employee_id=None,
                    additional_employer_rate=Decimal("2.00"),
                    effective_from=date(2026, 10, 1),
                )
            )

            session.add(
                Timesheet(
                    employee_id=None,
                    engagement_id=engagement.id,
                    assignment_id=assignment.id,
                    work_date=date(2026, 10, 16),
                    hours_worked=Decimal("11.00"),
                    status="approved",
                )
            )

            pay_run = PayRun(
                organisation_id=employer.id,
                period_start=date(2026, 10, 12),
                period_end=date(2026, 10, 18),
                payment_date=date(2026, 10, 19),
                status="draft",
            )
            session.add(pay_run)
            session.commit()

            with patch(
                "app.payroll.pay_run_processor."
                "PAYGWithholdingCalculator.calculate",
                return_value=Decimal("43.00"),
            ):
                result = PayRunProcessor().process(
                    session=session,
                    pay_run_id=pay_run.id,
                )

            assert result == {"processed": 1, "skipped": 0}

            payslip = session.scalar(
                select(Payslip).where(
                    Payslip.pay_run_id == pay_run.id,
                    Payslip.engagement_id == engagement.id,
                )
            )

            components = session.scalars(
                select(PayrollComponent).where(
                    PayrollComponent.payslip_id == payslip.id
                )
            ).all()

            yield session, employer, worker, pay_run, payslip, components

    finally:
        engine.dispose()


def test_weekly_payroll_components_reconcile(payroll_data):
    session, employer, worker, pay_run, payslip, components = payroll_data

    amounts = {
        session.get(
            ComponentDefinition,
            component.component_definition_id,
        ).code: component.amount
        for component in components
    }

    assert len(components) == 4

    assert amounts == {
        "ORDINARY_HOURS": Decimal("605.00"),
        "PAYG_WITHHOLDING": Decimal("43.00"),
        "SUPER_GUARANTEE": Decimal("72.60"),
        "SUPER_EMPLOYER_EXTRA": Decimal("12.10"),
    }

    assert payslip.gross_pay == amounts["ORDINARY_HOURS"]
    assert payslip.payg_withholding == amounts["PAYG_WITHHOLDING"]
    assert payslip.net_pay == Decimal("562.00")

    assert payslip.superannuation == (
        amounts["SUPER_GUARANTEE"]
        + amounts["SUPER_EMPLOYER_EXTRA"]
    )


def test_payslip_pdf_component_sections(payroll_data):
    session, employer, worker, pay_run, payslip, components = payroll_data

    earnings_lines = []
    withholding_lines = []
    employer_super_lines = []

    for component in components:
        definition = session.get(
            ComponentDefinition,
            component.component_definition_id,
        )

        line = {
            "assignment": "#1",
            "component": definition.name,
            "quantity": component.quantity,
            "rate": component.rate,
            "amount": component.amount,
        }

        if definition.code == "ORDINARY_HOURS":
            earnings_lines.append(line)
        elif definition.code == "PAYG_WITHHOLDING":
            withholding_lines.append(line)
        else:
            employer_super_lines.append(line)

    assert len(earnings_lines) == 1
    assert len(withholding_lines) == 1
    assert len(employer_super_lines) == 2

    pdf = PayslipPDFGenerator().generate(
        payslip=payslip,
        employee=worker,
        organisation=employer,
        pay_run=pay_run,
        earnings_lines=earnings_lines,
        withholding_lines=withholding_lines,
        employer_super_lines=employer_super_lines,
    )

    assert isinstance(pdf, BytesIO)
    assert pdf.getvalue().startswith(b"%PDF")
    assert len(pdf.getvalue()) > 1000
