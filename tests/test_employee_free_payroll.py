
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.work_pattern import WorkPattern
from app.models.timesheet import Timesheet
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.payslip_timesheet import PayslipTimesheet

from app.models.assignment import Assignment
from app.models.assignment_component import AssignmentComponent
from app.models.component_family import ComponentFamily
from app.models.component_definition import ComponentDefinition
from app.models.payroll_component import PayrollComponent
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.timesheet_header import TimesheetHeader

from app.payroll.pay_run_processor import PayRunProcessor


def test_payroll_without_employee_record():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        organisation = Organisation(
            name="Employee Free Organisation",
            abn="98765432109",
            country="AU",
        )
        session.add(organisation)
        session.flush()

        worker = Worker(
            first_name="Sara",
            last_name="Ali",
            email="sara@example.com",
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

        assert session.scalar(
            select(func.count()).select_from(Worker)
        ) >= 1

        pattern = WorkPattern(
            engagement_id=engagement.id,
            employee_id=None,
            employment_type="full_time",
            pay_basis="hourly",
            hourly_rate=Decimal("50.00"),
            ordinary_hours_per_week=Decimal("38.00"),
            pay_frequency="fortnightly",
            start_date=date(2026, 10, 1),
            end_date=None,
        )
        session.add(pattern)

        for day in (1, 2):
            session.add(
                Timesheet(
                    engagement_id=engagement.id,
                    employee_id=None,
                    work_date=date(2026, 10, day),
                    hours_worked=Decimal("8.00"),
                    status="approved",
                )
            )

        pay_run = PayRun(
            organisation_id=organisation.id,
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 14),
            payment_date=date(2026, 10, 15),
            status="draft",
        )
        session.add(pay_run)
        session.commit()

        expected = {
            "gross_pay": Decimal("800.00"),
            "payg_withholding": Decimal("100.00"),
            "net_pay": Decimal("700.00"),
            "superannuation": Decimal("96.00"),
        }

        with patch(
            "app.payroll.pay_run_processor.PayrollEngine.calculate",
            return_value=expected,
        ) as calculate:
            result = PayRunProcessor().process(
                session=session,
                pay_run_id=pay_run.id,
            )

        assert result["processed"] == 1
        assert result["skipped"] == 0

        calculate.assert_called_once()
        assert calculate.call_args.kwargs["hours_worked"] == Decimal("16.00")

        payslip = session.scalar(
            select(Payslip).where(
                Payslip.pay_run_id == pay_run.id,
                Payslip.engagement_id == engagement.id,
            )
        )

        assert payslip is not None
        assert payslip.employee_id is None
        assert payslip.engagement_id == engagement.id

        assert payslip.gross_pay == expected["gross_pay"]
        assert payslip.payg_withholding == expected["payg_withholding"]
        assert payslip.net_pay == expected["net_pay"]
        assert payslip.superannuation == expected["superannuation"]

        links = session.scalars(
            select(PayslipTimesheet).where(
                PayslipTimesheet.payslip_id == payslip.id
            )
        ).all()

        assert len(links) == 2

        assert session.scalar(
            select(func.count()).select_from(Worker)
        ) >= 1
