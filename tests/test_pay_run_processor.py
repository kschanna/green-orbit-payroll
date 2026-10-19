from datetime import date
from unittest.mock import MagicMock

import pytest

from app.models.pay_run import PayRun
from app.payroll.pay_run_processor import PayRunProcessor
from app.models.timesheet import Timesheet


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



from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.models.payslip_timesheet import PayslipTimesheet
from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.work_pattern import WorkPattern
from app.models.payslip import Payslip


def test_draft_payslip_is_recalculated():

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

        worker = Worker(
            first_name="Ahmed",
            last_name="Khan",
            email="ahmed@test.com",
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

        agreement = WorkPattern(
            employee_id=None,
            engagement_id=engagement.id,
            employment_type="full_time",
            pay_basis="hourly",
            hourly_rate=Decimal("45.00"),
            ordinary_hours_per_week=Decimal("38.00"),
            pay_frequency="fortnightly",
            start_date=date(2026, 10, 1),
            end_date=None
        )
        session.add(agreement)

        # Four approved timesheets totalling 30 hours
        for day, hours in enumerate(["7.50"] * 4, start=1):
            session.add(
                Timesheet(
                    employee_id=None,
                    engagement_id=engagement.id,
                    work_date=date(2026, 10, day),
                    hours_worked=Decimal(hours),
                    status="approved"
                )
            )

        pay_run = PayRun(
            organisation_id=organisation.id,
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 14),
            payment_date=date(2026, 10, 15),
            status="draft"
        )
        session.add(pay_run)
        session.commit()

        with patch(
            "app.payroll.engine.PAYGWithholdingCalculator.calculate",
            return_value=Decimal("200.00")
        ):

            # First processing: 30 hours
            first_result = PayRunProcessor().process(
                session=session,
                pay_run_id=pay_run.id
            )

            assert first_result["processed"] == 1

            first_payslip = session.scalar(
                select(Payslip).where(
                    Payslip.pay_run_id == pay_run.id
                )
            )

            assert first_payslip.gross_pay == Decimal("1350.00")
            assert first_payslip.engagement_id == engagement.id

            # Approve an additional 8 hours
            additional_timesheet = Timesheet(
                employee_id=None,
                engagement_id=engagement.id,
                work_date=date(2026, 10, 5),
                hours_worked=Decimal("8.00"),
                status="approved"
            )
            session.add(additional_timesheet)
            session.commit()

            # Reprocess the same draft pay run
            second_result = PayRunProcessor().process(
                session=session,
                pay_run_id=pay_run.id
            )

        assert second_result["processed"] == 1

        payslips = session.scalars(
            select(Payslip).where(
                Payslip.pay_run_id == pay_run.id
            )
        ).all()

        # Still only one payslip, recalculated for 38 hours
        assert len(payslips) == 1
        assert payslips[0].gross_pay == Decimal("1710.00")
        assert payslips[0].engagement_id == engagement.id

        # Both approved timesheets are linked
        links = session.scalars(
            select(PayslipTimesheet).where(
                PayslipTimesheet.payslip_id == payslips[0].id
            )
        ).all()

        assert len(links) == 5


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

            worker = Worker(
                first_name=first_name,
                last_name=last_name,
                email=email,
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

            agreement = WorkPattern(
                employee_id=None,
                engagement_id=engagement.id,
                employment_type="full_time",
                pay_basis="hourly",
                hourly_rate=Decimal(hourly_rate),
                ordinary_hours_per_week=Decimal("38.00"),
                pay_frequency="fortnightly",
                start_date=date(2026, 10, 1),
                end_date=None
            )

            session.add(agreement)

            # Create 10 approved timesheets for each employee
            for day in range(1, 11):
                timesheet = Timesheet(
                    employee_id=None,
                    engagement_id=engagement.id,
                    work_date=date(2026, 10, day),
                    hours_worked=Decimal("7.60"),
                    status="approved"
                )

                session.add(timesheet)

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
        assert all(
            p.engagement_id is not None
            for p in payslips
        )

        gross_amounts = sorted(
            payslip.gross_pay for payslip in payslips
        )

        assert gross_amounts == [
            Decimal("3420.00"),
            Decimal("4180.00")
        ]