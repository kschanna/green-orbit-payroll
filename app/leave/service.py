from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select

from app.models.component_definition import ComponentDefinition
from app.models.engagement import Engagement
from app.models.leave_plan import LeavePlan
from app.models.leave_transaction import LeaveTransaction
from app.models.payroll_component import PayrollComponent
from app.models.payslip import Payslip
from app.models.payslip_timesheet import PayslipTimesheet
from app.models.pay_run import PayRun
from app.models.timesheet import Timesheet


FOUR_PLACES = Decimal("0.0001")


class LeaveService:
    @staticmethod
    def balance(session, plan_id):
        plan = session.get(LeavePlan, plan_id)
        if plan is None:
            raise ValueError("Leave plan not found")
        posted = session.scalar(
            select(func.coalesce(func.sum(LeaveTransaction.hours), 0)).where(
                LeaveTransaction.leave_plan_id == plan_id
            )
        )
        return Decimal(plan.opening_balance_hours) + Decimal(posted or 0)

    @staticmethod
    def active_plan(session, engagement_id, component_definition_id, on_date):
        plans = session.scalars(
            select(LeavePlan).where(
                LeavePlan.engagement_id == engagement_id,
                LeavePlan.component_definition_id == component_definition_id,
                LeavePlan.status == "active",
                LeavePlan.effective_from <= on_date,
                (LeavePlan.effective_to.is_(None) | (LeavePlan.effective_to >= on_date)),
            )
        ).all()
        if len(plans) != 1:
            raise ValueError(
                f"Expected exactly one effective leave plan; found {len(plans)}"
            )
        return plans[0]

    @classmethod
    def validate_timesheets(cls, session, engagement_id, timesheets):
        requested = {}
        for row in timesheets:
            if row.component_definition_id is None or row.hours_worked <= 0:
                continue
            definition = session.get(ComponentDefinition, row.component_definition_id)
            if definition is None or definition.code not in {"ANNUAL_LEAVE", "PERSONAL_LEAVE"}:
                continue
            plan = cls.active_plan(
                session, engagement_id, definition.id, row.work_date
            )
            requested[plan.id] = requested.get(plan.id, Decimal("0")) + Decimal(row.hours_worked)

        submitted_ids = [row.id for row in timesheets if row.id is not None]
        for plan_id, hours in requested.items():
            plan = session.get(LeavePlan, plan_id)
            paid_ids = select(PayslipTimesheet.timesheet_id).join(
                Payslip, Payslip.id == PayslipTimesheet.payslip_id
            ).join(PayRun, PayRun.id == Payslip.pay_run_id).where(
                PayRun.status == "completed"
            )
            reserved_query = select(
                func.coalesce(func.sum(Timesheet.hours_worked), 0)
            ).where(
                Timesheet.engagement_id == engagement_id,
                Timesheet.component_definition_id == plan.component_definition_id,
                Timesheet.status == "approved",
                Timesheet.id.not_in(paid_ids),
            )
            if submitted_ids:
                reserved_query = reserved_query.where(
                    Timesheet.id.not_in(submitted_ids)
                )
            reserved = Decimal(session.scalar(reserved_query) or 0)
            if (
                not plan.allow_negative_balance
                and hours + reserved > cls.balance(session, plan_id)
            ):
                raise ValueError("Insufficient leave balance")

    @classmethod
    def post_pay_run(cls, session, pay_run):
        payslips = session.scalars(
            select(Payslip).where(Payslip.pay_run_id == pay_run.id)
        ).all()
        for payslip in payslips:
            engagement = session.get(Engagement, payslip.engagement_id)
            if (
                engagement is None
                or engagement.engagement_type not in {
                    "payg_employee", "payg_contractor"
                }
            ):
                continue
            plans = session.scalars(
                select(LeavePlan).where(
                    LeavePlan.engagement_id == payslip.engagement_id,
                    LeavePlan.status == "active",
                    LeavePlan.effective_from <= pay_run.payment_date,
                    (LeavePlan.effective_to.is_(None) | (LeavePlan.effective_to >= pay_run.payment_date)),
                )
            ).all()
            components = session.execute(
                select(PayrollComponent, ComponentDefinition)
                .join(ComponentDefinition, ComponentDefinition.id == PayrollComponent.component_definition_id)
                .where(PayrollComponent.payslip_id == payslip.id)
            ).all()
            eligible_hours = sum(
                (Decimal(c.quantity) for c, d in components if d.code == "ORDINARY_HOURS"),
                Decimal("0"),
            )
            paid_leave_hours = sum(
                (Decimal(c.quantity) for c, d in components if d.code in {"ANNUAL_LEAVE", "PERSONAL_LEAVE"}),
                Decimal("0"),
            )
            for plan in plans:
                basis = eligible_hours
                if plan.accrues_during_paid_leave:
                    basis += paid_leave_hours
                accrued = (basis * Decimal(plan.accrual_rate_per_hour)).quantize(
                    FOUR_PLACES, rounding=ROUND_HALF_UP
                )
                cls._add_once(
                    session, plan, pay_run.payment_date, "accrual", accrued,
                    "pay_run", pay_run.id, f"Accrual for pay run #{pay_run.id}",
                )

            links = session.scalars(
                select(PayslipTimesheet).where(PayslipTimesheet.payslip_id == payslip.id)
            ).all()
            for link in links:
                row = session.get(Timesheet, link.timesheet_id)
                if row is None or row.component_definition_id is None:
                    continue
                definition = session.get(ComponentDefinition, row.component_definition_id)
                if definition is None or definition.code not in {"ANNUAL_LEAVE", "PERSONAL_LEAVE"}:
                    continue
                plan = cls.active_plan(
                    session, payslip.engagement_id, definition.id, row.work_date
                )
                cls._add_once(
                    session, plan, row.work_date, "leave_taken",
                    -Decimal(row.hours_worked), "timesheet", row.id,
                    f"{definition.name} taken",
                )

    @staticmethod
    def _add_once(session, plan, transaction_date, transaction_type, hours,
                  source_type, source_id, description):
        existing = session.scalar(
            select(LeaveTransaction.id).where(
                LeaveTransaction.leave_plan_id == plan.id,
                LeaveTransaction.source_type == source_type,
                LeaveTransaction.source_id == source_id,
                LeaveTransaction.transaction_type == transaction_type,
            )
        )
        if existing is None and hours != 0:
            session.add(LeaveTransaction(
                leave_plan_id=plan.id, transaction_date=transaction_date,
                transaction_type=transaction_type, hours=hours,
                source_type=source_type, source_id=source_id,
                description=description,
            ))
