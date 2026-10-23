from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.leave.service import LeaveService
from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.component_family import ComponentFamily
from app.models.component_definition import ComponentDefinition
from app.models.leave_plan import LeavePlan
from app.models.leave_transaction import LeaveTransaction
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.payroll_component import PayrollComponent
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.payslip_timesheet import PayslipTimesheet
from app.models.assignment import Assignment
from app.models.invoice import Invoice
from app.models.invoice_timesheet import InvoiceTimesheet
from app.models.invoice_component import InvoiceComponent
from app.models.assignment_component import AssignmentComponent
from app.models.component_base import ComponentBase
from app.models.component_base_member import ComponentBaseMember
from app.models.component_audit_log import ComponentAuditLog
from app.models.user import User
from app.models.work_pattern import WorkPattern
from app.models.payg_tax_table import PAYGTaxTable
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.employee_payment_detail import EmployeePaymentDetail
from app.models.employee_tfn import EmployeeTFN
from app.models.employee_tfn_audit import EmployeeTFNAudit
from app.leave_router import update_worker_leave_plan


@pytest.fixture
def leave_data():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        organisation = Organisation(name="Employer", abn="11111111111")
        worker = Worker(first_name="Lea", last_name="Ve", email="leave@example.com")
        db.add_all([organisation, worker])
        db.flush()
        engagement = Engagement(
            worker_id=worker.id, organisation_id=organisation.id,
            engagement_type="payg_employee", status="active",
        )
        family = ComponentFamily(code="LEAVE", name="Leave")
        earnings = ComponentFamily(code="EARNINGS", name="Earnings")
        tax_family = ComponentFamily(code="TAX", name="Tax")
        super_family = ComponentFamily(code="SUPERANNUATION", name="Superannuation")
        db.add_all([engagement, family, earnings, tax_family, super_family])
        db.flush()
        annual = ComponentDefinition(
            family_id=family.id, code="ANNUAL_LEAVE", name="Annual Leave",
            calculation_type="hourly", active=True,
        )
        ordinary = ComponentDefinition(
            family_id=earnings.id, code="ORDINARY_HOURS", name="Ordinary Hours",
            calculation_type="hourly", active=True,
        )
        payg = ComponentDefinition(
            family_id=tax_family.id, code="PAYG_WITHHOLDING", name="PAYG",
            calculation_type="fixed", active=True,
        )
        super_guarantee = ComponentDefinition(
            family_id=super_family.id, code="SUPER_GUARANTEE", name="Super",
            calculation_type="percentage", active=True,
        )
        super_extra = ComponentDefinition(
            family_id=super_family.id, code="SUPER_EMPLOYER_EXTRA", name="Extra Super",
            calculation_type="percentage", active=True,
        )
        db.add_all([annual, ordinary, payg, super_guarantee, super_extra])
        db.flush()
        plan = LeavePlan(
            worker_id=worker.id, engagement_id=engagement.id,
            component_definition_id=annual.id,
            annual_entitlement_hours=Decimal("152"),
            standard_hours_per_year=Decimal("1976"),
            accrual_rate_per_hour=Decimal("152") / Decimal("1976"),
            opening_balance_hours=Decimal("20"),
            allow_negative_balance=False, accrues_during_paid_leave=True,
            effective_from=date(2026, 1, 1), status="active",
        )
        db.add(plan)
        db.add_all([
            WorkPattern(
                engagement_id=engagement.id, employment_type="full_time",
                pay_basis="hourly", hourly_rate=Decimal("50"),
                ordinary_hours_per_week=Decimal("38"), pay_frequency="weekly",
                start_date=date(2026, 1, 1),
            ),
            EmployeeTaxProfile(
                worker_id=worker.id, engagement_id=engagement.id,
                residency_status="resident", claims_tax_free_threshold=True,
                has_study_loan=False, tfn_declaration_received=True,
                effective_from=date(2026, 1, 1),
            ),
            EmployeeSuperProfile(
                worker_id=worker.id, engagement_id=engagement.id,
                additional_employer_rate=Decimal("0"),
                effective_from=date(2026, 1, 1),
            ),
            PAYGTaxTable(
                pay_frequency="weekly", claims_tax_free_threshold=True,
                gross_pay=Decimal("1900"), withholding_amount=Decimal("300"),
                effective_from=date(2026, 7, 1),
            ),
        ])
        db.commit()
        ids = {"engagement": engagement.id, "annual": annual.id,
               "ordinary": ordinary.id, "plan": plan.id,
               "organisation": organisation.id, "worker": worker.id}
    yield engine, ids
    engine.dispose()


def test_leave_balance_includes_opening_balance_and_ledger(leave_data):
    engine, ids = leave_data
    with Session(engine) as db:
        db.add(LeaveTransaction(
            leave_plan_id=ids["plan"], transaction_date=date(2026, 10, 1),
            transaction_type="adjustment", hours=Decimal("3.5"),
            source_type="manual", source_id=1,
        ))
        db.commit()
        assert LeaveService.balance(db, ids["plan"]) == Decimal("23.5000")


def test_worker_leave_plan_can_be_edited(leave_data, monkeypatch):
    engine, ids = leave_data
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.leave_router.SessionLocal", factory)
    monkeypatch.setattr("app.leave_router.require_csrf", lambda *_: None)

    response = update_worker_leave_plan(
        request=object(), worker_id=ids["worker"], plan_id=ids["plan"],
        engagement_id=ids["engagement"],
        component_definition_id=ids["annual"],
        annual_entitlement_hours=Decimal("190"),
        standard_hours_per_year=Decimal("1900"),
        opening_balance_hours=Decimal("25"),
        paid_leave_rate=None,
        effective_from=date(2026, 2, 1), effective_to=date(2026, 12, 31),
        allow_negative_balance=True, accrues_during_paid_leave=False,
        csrf_token="test",
    )

    assert response.status_code == 303
    with Session(engine) as db:
        plan = db.get(LeavePlan, ids["plan"])
        assert plan.annual_entitlement_hours == Decimal("190.0000")
        assert plan.accrual_rate_per_hour == Decimal("0.1000000000")
        assert plan.opening_balance_hours == Decimal("25.0000")
        assert plan.effective_from == date(2026, 2, 1)
        assert plan.effective_to == date(2026, 12, 31)
        assert plan.allow_negative_balance is True
        assert plan.accrues_during_paid_leave is False


def test_leave_validation_rejects_insufficient_balance(leave_data):
    engine, ids = leave_data
    with Session(engine) as db:
        row = Timesheet(
            engagement_id=ids["engagement"],
            component_definition_id=ids["annual"],
            work_date=date(2026, 10, 12), hours_worked=Decimal("21"),
            status="draft",
        )
        with pytest.raises(ValueError, match="Insufficient leave balance"):
            LeaveService.validate_timesheets(db, ids["engagement"], [row])


def test_completed_pay_run_posts_accrual_and_leave_once(leave_data):
    engine, ids = leave_data
    with Session(engine) as db:
        pay_run = PayRun(
            organisation_id=ids["organisation"],
            period_start=date(2026, 10, 12), period_end=date(2026, 10, 18),
            payment_date=date(2026, 10, 19), status="approved",
        )
        db.add(pay_run)
        db.flush()
        payslip = Payslip(
            engagement_id=ids["engagement"], pay_run_id=pay_run.id,
            gross_pay=Decimal("1900"), payg_withholding=Decimal("300"),
            net_pay=Decimal("1600"), superannuation=Decimal("228"),
        )
        db.add(payslip)
        db.flush()
        db.add_all([
            PayrollComponent(
                payslip_id=payslip.id, component_definition_id=ids["ordinary"],
                quantity=Decimal("30"), rate=Decimal("50"), amount=Decimal("1500"),
            ),
            PayrollComponent(
                payslip_id=payslip.id, component_definition_id=ids["annual"],
                quantity=Decimal("8"), rate=Decimal("50"), amount=Decimal("400"),
            ),
        ])
        row = Timesheet(
            engagement_id=ids["engagement"],
            component_definition_id=ids["annual"],
            work_date=date(2026, 10, 13), hours_worked=Decimal("8"),
            status="approved",
        )
        db.add(row)
        db.flush()
        db.add(PayslipTimesheet(payslip_id=payslip.id, timesheet_id=row.id))
        db.commit()

        LeaveService.post_pay_run(db, pay_run)
        LeaveService.post_pay_run(db, pay_run)
        db.commit()
        transactions = db.scalars(select(LeaveTransaction)).all()
        assert len(transactions) == 2
        assert {t.transaction_type for t in transactions} == {"accrual", "leave_taken"}
        accrual = next(t for t in transactions if t.transaction_type == "accrual")
        assert accrual.hours == Decimal("2.9231")
        assert LeaveService.balance(db, ids["plan"]) == Decimal("14.9231")


def test_payg_weekly_leave_replaces_ordinary_hours(leave_data):
    from app.payroll.pay_run_processor import PayRunProcessor

    engine, ids = leave_data
    with Session(engine) as db:
        leave = Timesheet(
            engagement_id=ids["engagement"],
            component_definition_id=ids["annual"],
            work_date=date(2026, 10, 13), hours_worked=Decimal("8"),
            status="approved",
        )
        pay_run = PayRun(
            organisation_id=ids["organisation"],
            period_start=date(2026, 10, 12), period_end=date(2026, 10, 18),
            payment_date=date(2026, 10, 19), status="draft",
        )
        db.add_all([leave, pay_run])
        db.commit()

        assert PayRunProcessor().process(db, pay_run.id) == {
            "processed": 1, "skipped": 0,
        }
        payslip = db.scalar(select(Payslip).where(Payslip.pay_run_id == pay_run.id))
        assert payslip.gross_pay == Decimal("1900.00")
        components = db.execute(
            select(PayrollComponent, ComponentDefinition)
            .join(ComponentDefinition, ComponentDefinition.id == PayrollComponent.component_definition_id)
            .where(PayrollComponent.payslip_id == payslip.id)
        ).all()
        quantities = {definition.code: component.quantity for component, definition in components}
        assert quantities["ORDINARY_HOURS"] == Decimal("30.0000")
        assert quantities["ANNUAL_LEAVE"] == Decimal("8.0000")
        assert db.scalar(select(PayslipTimesheet.timesheet_id).where(
            PayslipTimesheet.payslip_id == payslip.id
        )) == leave.id
