from datetime import date
from unittest.mock import MagicMock

import pytest

from app.models.pay_run import PayRun
from app.payroll.pay_run_processor import PayRunProcessor


def test_missing_pay_run():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(ValueError, match="Pay run not found"):
        PayRunProcessor().process(session, pay_run_id=999)


def test_non_draft_pay_run():
    session = MagicMock()

    pay_run = PayRun(
        organisation_id=1,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 14),
        payment_date=date(2026, 10, 15),
        status="completed"
    )

    session.get.return_value = pay_run

    with pytest.raises(ValueError, match="Only draft pay runs"):
        PayRunProcessor().process(session, pay_run_id=1)


def test_invalid_pay_period():
    session = MagicMock()

    pay_run = PayRun(
        organisation_id=1,
        period_start=date(2026, 10, 14),
        period_end=date(2026, 10, 1),
        payment_date=date(2026, 10, 15),
        status="draft"
    )

    session.get.return_value = pay_run

    with pytest.raises(ValueError, match="Pay period end"):
        PayRunProcessor().process(session, pay_run_id=1)


def test_invalid_payment_date():
    session = MagicMock()

    pay_run = PayRun(
        organisation_id=1,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 14),
        payment_date=date(2026, 10, 10),
        status="draft"
    )

    session.get.return_value = pay_run

    with pytest.raises(ValueError, match="Payment date"):
        PayRunProcessor().process(session, pay_run_id=1)



from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base, Organisation
from app.models.employee import Employee
from app.models.employment_agreement import EmploymentAgreement
from app.models.payslip import Payslip


def test_existing_payslip_is_skipped():

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:

        organisation = Organisation(
            name="Test Organisation",
            abn="12345678901",
            country="AU"
        )

        session.add(organisation)
        session.flush()

        employee = Employee(
            organisation_id=organisation.id,
            first_name="Ahmed",
            last_name="Khan",
            email="ahmed@test.com"
        )

        session.add(employee)
        session.flush()

        pay_run = PayRun(
            organisation_id=organisation.id,
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 14),
            payment_date=date(2026, 10, 15),
            status="draft"
        )

        session.add(pay_run)
        session.flush()

        payslip = Payslip(
            pay_run_id=pay_run.id,
            employee_id=employee.id,
            gross_pay=3420,
            payg_withholding=732,
            net_pay=2688,
            superannuation=410.40
        )

        session.add(payslip)
        session.commit()

        result = PayRunProcessor().process(
            session=session,
            pay_run_id=pay_run.id
        )

        assert result["processed"] == 0
        assert result["skipped"] == 1


from decimal import Decimal
from unittest.mock import patch

def test_process_multiple_employees():

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:

        organisation = Organisation(
            name="Test Organisation",
            abn="12345678901",
            country="AU"
        )

        session.add(organisation)
        session.flush()

        employees = [
            ("Ahmed", "Khan", "ahmed@test.com", "45.00"),
            ("Sarah", "Mitchell", "sarah@test.com", "55.00")
        ]

        for first_name, last_name, email, hourly_rate in employees:

            employee = Employee(
                organisation_id=organisation.id,
                first_name=first_name,
                last_name=last_name,
                email=email
            )

            session.add(employee)
            session.flush()

            agreement = EmploymentAgreement(
                employee_id=employee.id,
                employment_type="full_time",
                pay_basis="hourly",
                hourly_rate=Decimal(hourly_rate),
                ordinary_hours_per_week=Decimal("38.00"),
                pay_frequency="fortnightly",
                start_date=date(2026, 10, 1),
                end_date=None
            )

            session.add(agreement)

        pay_run = PayRun(
            organisation_id=organisation.id,
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 14),
            payment_date=date(2026, 10, 15),
            status="draft"
        )

        session.add(pay_run)
        session.commit()

        # Mock PAYG so we don't need ATO tables in this test
        with patch(
            "app.payroll.engine.PAYGWithholdingCalculator.calculate",
            return_value=Decimal("732.00")
        ):

            result = PayRunProcessor().process(
                session=session,
                pay_run_id=pay_run.id
            )

        assert result["processed"] == 2
        assert result["skipped"] == 0

        payslips = session.query(Payslip).all()

        assert len(payslips) == 2

        gross_amounts = sorted(
            payslip.gross_pay for payslip in payslips
        )

        assert gross_amounts == [
            Decimal("3420.00"),
            Decimal("4180.00")
        ]