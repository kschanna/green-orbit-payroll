
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
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
from app.models.payg_tax_table import PAYGTaxTable
from app.models.timesheet import Timesheet
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.payslip_timesheet import PayslipTimesheet
from app.models.payroll_component import PayrollComponent

from app.payroll.pay_run_processor import PayRunProcessor


def test_complete_weekly_payroll_without_employee():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            employer = Organisation(
                name="Employee-Free Employer",
                abn="12345678901",
                country="AU",
            )
            customer = Organisation(
                name="Employee-Free Customer",
                abn="98765432109",
                country="AU",
            )
            session.add_all([employer, customer])
            session.flush()

            worker = Worker(
                first_name="Sara",
                last_name="Ali",
                email="sara.weekly@example.com",
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
                ("SUPER_EMPLOYER_EXTRA", "Additional Employer Super",
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
                engagement_id=engagement.id,
                employee_id=None,
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
                    worker_id=worker.id,
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
                    worker_id=worker.id,
                    employee_id=None,
                    additional_employer_rate=Decimal("2.00"),
                    effective_from=date(2026, 10, 1),
                )
            )

            # Synthetic PAYG fixture: tests real lookup, not ATO accuracy.
            session.add_all([
                PAYGTaxTable(
                    pay_frequency="weekly",
                    claims_tax_free_threshold=True,
                    gross_pay=Decimal("600.00"),
                    withholding_amount=Decimal("43.00"),
                    effective_from=date(2026, 7, 1),
                ),
                PAYGTaxTable(
                    pay_frequency="weekly",
                    claims_tax_free_threshold=True,
                    gross_pay=Decimal("610.00"),
                    withholding_amount=Decimal("45.00"),
                    effective_from=date(2026, 7, 1),
                ),
            ])

            timesheet = Timesheet(
                engagement_id=engagement.id,
                employee_id=None,
                assignment_id=assignment.id,
                work_date=date(2026, 10, 16),
                hours_worked=Decimal("11.00"),
                status="approved",
            )
            session.add(timesheet)

            pay_run = PayRun(
                organisation_id=employer.id,
                period_start=date(2026, 10, 12),
                period_end=date(2026, 10, 18),
                payment_date=date(2026, 10, 19),
                status="draft",
            )
            session.add(pay_run)
            session.commit()

            assert session.scalar(
                select(func.count()).select_from(Worker)
            ) >= 1

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

            assert payslip is not None
            assert payslip.employee_id is None
            assert payslip.engagement_id == engagement.id

            assert payslip.gross_pay == Decimal("605.00")
            assert payslip.payg_withholding == Decimal("43.00")
            assert payslip.net_pay == Decimal("562.00")
            assert payslip.superannuation == Decimal("84.70")

            components = session.scalars(
                select(PayrollComponent).where(
                    PayrollComponent.payslip_id == payslip.id
                )
            ).all()

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

            links = session.scalars(
                select(PayslipTimesheet).where(
                    PayslipTimesheet.payslip_id == payslip.id
                )
            ).all()

            assert len(links) == 1
            assert links[0].timesheet_id == timesheet.id

            assert session.scalar(
                select(func.count()).select_from(Worker)
            ) >= 1

    finally:
        engine.dispose()
