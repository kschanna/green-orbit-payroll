
from datetime import timedelta

from app.models.assignment import Assignment
from app.models.assignment_component import AssignmentComponent
from app.models.component_definition import ComponentDefinition
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.payroll_component import PayrollComponent

from app.payroll.assignment_earnings import AssignmentEarningsCalculator
from app.payroll.payg_withholding import PAYGWithholdingCalculator
from app.payroll.superannuation import SuperannuationCalculator

from decimal import Decimal

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.models.engagement import Engagement
from app.models.work_pattern import WorkPattern
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.timesheet import Timesheet
from app.models.payslip_timesheet import PayslipTimesheet

from app.payroll.engine import PayrollEngine


class PayRunProcessor:

    def _is_assignment_weekly(self, pay_run):
        return (
            pay_run.period_start.weekday() == 0
            and pay_run.period_end
            == pay_run.period_start + timedelta(days=6)
        )



    def _process_payg_employee_weekly(
        self,
        session,
        pay_run,
        engagement,
    ):
        """
        PAYG Employee ordinary earnings come exclusively
        from the Engagement Work Pattern.

        Timesheets are NOT the ordinary-pay source.
        """

        from decimal import ROUND_HALF_UP

        if engagement.engagement_type != "payg_employee":
            raise ValueError(
                "Invalid Engagement type for PAYG Employee payroll"
            )

        if engagement.status != "active":
            return 0

        if not engagement.worker.active:
            return 0

        if (
            engagement.start_date is not None
            and engagement.start_date > pay_run.period_start
        ):
            raise ValueError(
                f"Engagement {engagement.id}: "
                "partial-period payroll is not yet supported"
            )

        if (
            engagement.end_date is not None
            and engagement.end_date < pay_run.period_end
        ):
            raise ValueError(
                f"Engagement {engagement.id}: "
                "partial-period payroll is not yet supported"
            )

        patterns = session.scalars(
            select(WorkPattern).where(
                WorkPattern.engagement_id == engagement.id,
                WorkPattern.start_date <= pay_run.period_start,
                (
                    WorkPattern.end_date.is_(None)
                    | (
                        WorkPattern.end_date
                        >= pay_run.period_end
                    )
                ),
            )
        ).all()

        if len(patterns) != 1:
            raise ValueError(
                f"Engagement {engagement.id}: expected exactly "
                f"one Work Pattern covering the pay period; "
                f"found {len(patterns)}"
            )

        pattern = patterns[0]

        if pattern.pay_frequency != "weekly":
            raise ValueError(
                f"Engagement {engagement.id}: "
                "Work Pattern is not weekly"
            )

        if pattern.pay_basis != "hourly":
            raise ValueError(
                f"Engagement {engagement.id}: "
                "salary payroll not yet supported by this pathway"
            )

        hours = Decimal(pattern.ordinary_hours_per_week)
        rate = Decimal(pattern.hourly_rate)

        if hours <= 0 or rate <= 0:
            raise ValueError(
                f"Engagement {engagement.id}: invalid ordinary "
                "hours or hourly rate"
            )

        leave_definitions = {
            definition.id: definition
            for definition in session.scalars(
                select(ComponentDefinition).where(
                    ComponentDefinition.code.in_((
                        "ANNUAL_LEAVE", "PERSONAL_LEAVE"
                    ))
                )
            ).all()
        }
        leave_timesheets = session.scalars(
            select(Timesheet).where(
                Timesheet.engagement_id == engagement.id,
                Timesheet.work_date >= pay_run.period_start,
                Timesheet.work_date <= pay_run.period_end,
                Timesheet.status == "approved",
                Timesheet.component_definition_id.in_(leave_definitions),
            )
        ).all()
        from app.leave.service import LeaveService
        LeaveService.validate_timesheets(
            session, engagement.id, leave_timesheets
        )
        leave_hours_by_definition = {}
        for row in leave_timesheets:
            leave_hours_by_definition[row.component_definition_id] = (
                leave_hours_by_definition.get(
                    row.component_definition_id, Decimal("0")
                ) + Decimal(row.hours_worked)
            )
        total_leave_hours = sum(
            leave_hours_by_definition.values(), Decimal("0")
        )
        if total_leave_hours > hours:
            raise ValueError(
                f"Engagement {engagement.id}: leave hours exceed ordinary hours"
            )
        ordinary_hours = hours - total_leave_hours

        gross = (hours * rate).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        # Validate effective tax profile.
        tax_profiles = session.scalars(
            select(EmployeeTaxProfile).where(
                EmployeeTaxProfile.worker_id
                == engagement.worker_id,
                EmployeeTaxProfile.effective_from
                <= pay_run.payment_date,
                (
                    EmployeeTaxProfile.effective_to.is_(None)
                    | (
                        EmployeeTaxProfile.effective_to
                        >= pay_run.payment_date
                    )
                ),
            )
        ).all()

        if len(tax_profiles) != 1:
            raise ValueError(
                f"Engagement {engagement.id}: expected exactly "
                "one effective Tax Profile"
            )

        tax = tax_profiles[0]

        if tax.residency_status != "resident":
            raise ValueError(
                f"Engagement {engagement.id}: unsupported residency"
            )

        if tax.has_study_loan:
            raise ValueError(
                f"Engagement {engagement.id}: study loan "
                "withholding not yet supported"
            )

        if not tax.tfn_declaration_received:
            raise ValueError(
                f"Engagement {engagement.id}: "
                "TFN declaration missing"
            )

        payg = PAYGWithholdingCalculator().calculate(
            session=session,
            gross_pay=gross,
            pay_frequency="weekly",
            claims_tax_free_threshold=(
                tax.claims_tax_free_threshold
            ),
            payment_date=pay_run.payment_date,
        )

        # Validate effective superannuation profile.
        super_profiles = session.scalars(
            select(EmployeeSuperProfile).where(
                EmployeeSuperProfile.worker_id
                == engagement.worker_id,
                EmployeeSuperProfile.effective_from
                <= pay_run.payment_date,
                (
                    EmployeeSuperProfile.effective_to.is_(None)
                    | (
                        EmployeeSuperProfile.effective_to
                        >= pay_run.payment_date
                    )
                ),
            )
        ).all()

        if len(super_profiles) != 1:
            raise ValueError(
                f"Engagement {engagement.id}: expected exactly "
                "one effective Super Profile"
            )

        super_profile = super_profiles[0]

        statutory_super = SuperannuationCalculator().calculate(
            ordinary_time_earnings=gross
        )

        additional_rate = (
            super_profile.additional_employer_rate
            or Decimal("0")
        )

        if additional_rate < 0:
            raise ValueError(
                f"Engagement {engagement.id}: "
                "invalid additional super rate"
            )

        additional_super = SuperannuationCalculator().calculate(
            ordinary_time_earnings=gross,
            rate=additional_rate / Decimal("100"),
        )

        total_super = statutory_super + additional_super

        # Never silently replace an existing payslip.
        # Also prevent overlapping pay periods.
        existing = session.scalars(
            select(Payslip)
            .join(
                PayRun,
                Payslip.pay_run_id == PayRun.id,
            )
            .where(
                Payslip.engagement_id == engagement.id,
                PayRun.period_start <= pay_run.period_end,
                PayRun.period_end >= pay_run.period_start,
            )
        ).all()

        if existing:
            raise ValueError(
                f"Engagement {engagement.id}: overlapping "
                "payslip already exists"
            )

        # Resolve component definitions before creating
        # any payroll records.
        required_codes = (
            "ORDINARY_HOURS",
            "PAYG_WITHHOLDING",
            "SUPER_GUARANTEE",
            "SUPER_EMPLOYER_EXTRA",
        )

        definitions = {
            definition.code: definition
            for definition in session.scalars(
                select(ComponentDefinition).where(
                    ComponentDefinition.code.in_(required_codes)
                )
            )
        }

        missing = set(required_codes) - set(definitions)

        if missing:
            raise ValueError(
                "Missing payroll component definitions: "
                + str(sorted(missing))
            )

        net = gross - payg

        payslip = Payslip(
            pay_run_id=pay_run.id,
            engagement_id=engagement.id,
            employee_id=None,
            gross_pay=gross,
            payg_withholding=payg,
            net_pay=net,
            superannuation=total_super,
        )

        session.add(payslip)
        session.flush()

        ordinary_amount = (ordinary_hours * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        components = [
            (
                "ORDINARY_HOURS",
                ordinary_hours,
                rate,
                ordinary_amount,
            ),
            (
                "PAYG_WITHHOLDING",
                Decimal("1"),
                payg,
                payg,
            ),
            (
                "SUPER_GUARANTEE",
                gross,
                Decimal("0.12"),
                statutory_super,
            ),
            (
                "SUPER_EMPLOYER_EXTRA",
                gross,
                additional_rate / Decimal("100"),
                additional_super,
            ),
        ]

        for definition_id, leave_hours in leave_hours_by_definition.items():
            definition = leave_definitions[definition_id]
            leave_amount = (leave_hours * rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            components.append((
                definition.code, leave_hours, rate, leave_amount,
            ))
            definitions[definition.code] = definition

        for code, quantity, component_rate, amount in components:
            session.add(
                PayrollComponent(
                    payslip_id=payslip.id,
                    component_definition_id=definitions[code].id,
                    quantity=quantity,
                    rate=component_rate,
                    amount=amount,
                )
            )

        for timesheet in leave_timesheets:
            session.add(PayslipTimesheet(
                payslip_id=payslip.id, timesheet_id=timesheet.id
            ))

        return 1


    def _process_assignment_weekly(self, session, pay_run):

        if pay_run.period_start.weekday() != 0:
            raise ValueError("Weekly pay period must start on Monday")

        if pay_run.period_end != pay_run.period_start + timedelta(days=6):
            raise ValueError("Weekly pay period must end on Sunday")

        engagements = session.scalars(
            select(Engagement).where(
                Engagement.organisation_id == pay_run.organisation_id
            )
        ).all()

        processed = 0
        skipped = 0

        for engagement in engagements:

            # PAYG Employees are paid from Work Patterns,
            # never from Timesheets.
            if engagement.engagement_type == "payg_employee":
                result = self._process_payg_employee_weekly(
                    session=session,
                    pay_run=pay_run,
                    engagement=engagement,
                )

                processed += result
                skipped += 1 - result
                continue

            # Company Contractors belong to Accounts Payable.
            if engagement.engagement_type == "company_contractor":
                skipped += 1
                continue

            timesheets = session.scalars(
                select(Timesheet).where(
                    Timesheet.engagement_id == engagement.id,
                    Timesheet.work_date >= pay_run.period_start,
                    Timesheet.work_date <= pay_run.period_end,
                    Timesheet.status == "approved",
                    Timesheet.assignment_id.is_not(None)
                )
            ).all()

            if not timesheets:
                skipped += 1
                continue

            earnings = AssignmentEarningsCalculator().calculate(
                session=session,
                engagement=engagement,
                timesheets=timesheets
            )

            tax_profiles = session.scalars(
                select(EmployeeTaxProfile).where(
                    EmployeeTaxProfile.worker_id == engagement.worker_id,
                    EmployeeTaxProfile.effective_from <= pay_run.payment_date,
                    (
                        EmployeeTaxProfile.effective_to.is_(None)
                        | (
                            EmployeeTaxProfile.effective_to
                            >= pay_run.payment_date
                        )
                    )
                )
            ).all()

            if len(tax_profiles) != 1:
                raise ValueError(
                    f"Engagement {engagement.id}: expected exactly one "
                    "effective tax profile"
                )

            tax = tax_profiles[0]

            if tax.residency_status != "resident":
                raise ValueError(
                    f"Engagement {engagement.id}: unsupported tax residency"
                )

            if tax.has_study_loan:
                raise ValueError(
                    f"Engagement {engagement.id}: study loan withholding "
                    "not yet supported"
                )

            if not tax.tfn_declaration_received:
                raise ValueError(
                    f"Engagement {engagement.id}: TFN declaration missing"
                )

            super_profiles = session.scalars(
                select(EmployeeSuperProfile).where(
                    EmployeeSuperProfile.worker_id == engagement.worker_id,
                    EmployeeSuperProfile.effective_from <= pay_run.payment_date,
                    (
                        EmployeeSuperProfile.effective_to.is_(None)
                        | (
                            EmployeeSuperProfile.effective_to
                            >= pay_run.payment_date
                        )
                    )
                )
            ).all()

            if len(super_profiles) != 1:
                raise ValueError(
                    f"Engagement {engagement.id}: expected exactly one "
                    "effective superannuation profile"
                )

            super_profile = super_profiles[0]

            gross = earnings["gross_pay"]

            payg = PAYGWithholdingCalculator().calculate(
                session=session,
                gross_pay=gross,
                pay_frequency="weekly",
                claims_tax_free_threshold=tax.claims_tax_free_threshold,
                payment_date=pay_run.payment_date
            )

            statutory_super = SuperannuationCalculator().calculate(
                ordinary_time_earnings=gross
            )

            additional_rate = (
                super_profile.additional_employer_rate
                or Decimal("0")
            )

            if additional_rate < 0:
                raise ValueError(
                    f"Engagement {engagement.id}: invalid additional super rate"
                )

            additional_super = SuperannuationCalculator().calculate(
                ordinary_time_earnings=gross,
                rate=additional_rate / Decimal("100")
            )

            total_super = statutory_super + additional_super

            existing = session.scalar(
                select(Payslip).where(
                    Payslip.pay_run_id == pay_run.id,
                    Payslip.engagement_id == engagement.id
                )
            )

            if existing:
                session.execute(
                    delete(PayrollComponent).where(
                        PayrollComponent.payslip_id == existing.id
                    )
                )

                session.execute(
                    delete(PayslipTimesheet).where(
                        PayslipTimesheet.payslip_id == existing.id
                    )
                )

                session.delete(existing)
                session.flush()

            payslip = Payslip(
                engagement_id=engagement.id,
                pay_run_id=pay_run.id,
                
                gross_pay=gross,
                payg_withholding=payg,
                net_pay=gross - payg,
                superannuation=total_super
            )

            session.add(payslip)
            session.flush()

            # Resolve the existing statutory payroll component definitions.
            required_codes = (
                "PAYG_WITHHOLDING",
                "SUPER_GUARANTEE",
                "SUPER_EMPLOYER_EXTRA",
            )

            definitions = {
                definition.code: definition
                for definition in session.scalars(
                    select(ComponentDefinition).where(
                        ComponentDefinition.code.in_(required_codes)
                    )
                )
            }

            missing_codes = set(required_codes) - set(definitions)

            if missing_codes:
                raise ValueError(
                    f"Missing payroll component definitions: "
                    f"{sorted(missing_codes)}"
                )

            for line in earnings["lines"]:
                session.add(
                    PayrollComponent(
                        payslip_id=payslip.id,
                        component_definition_id=line[
                            "component_definition_id"
                        ],
                        quantity=line["quantity"],
                        rate=line["rate"],
                        amount=line["amount"]
                    )
                )

            # Persist PAYG and employer super as realised payroll components.
            statutory_components = (
                (
                    "PAYG_WITHHOLDING",
                    Decimal("1"),
                    payg,
                    payg,
                ),
                (
                    "SUPER_GUARANTEE",
                    gross,
                    Decimal("0.12"),
                    statutory_super,
                ),
                (
                    "SUPER_EMPLOYER_EXTRA",
                    gross,
                    additional_rate / Decimal("100"),
                    additional_super,
                ),
            )

            for code, quantity, rate, amount in statutory_components:
                session.add(
                    PayrollComponent(
                        payslip_id=payslip.id,
                        component_definition_id=definitions[code].id,
                        quantity=quantity,
                        rate=rate,
                        amount=amount,
                    )
                )

            # Reconcile the realised component amounts.
            earnings_total = sum(
                (line["amount"] for line in earnings["lines"]),
                Decimal("0"),
            )

            if earnings_total != gross:
                raise ValueError(
                    f"Engagement {engagement.id}: earnings do not reconcile"
                )

            if gross - payg != payslip.net_pay:
                raise ValueError(
                    f"Engagement {engagement.id}: net pay does not reconcile"
                )

            if statutory_super + additional_super != total_super:
                raise ValueError(
                    f"Engagement {engagement.id}: super does not reconcile"
                )

            for timesheet in timesheets:
                session.add(
                    PayslipTimesheet(
                        payslip_id=payslip.id,
                        timesheet_id=timesheet.id
                    )
                )

            processed += 1

        session.commit()

        return {
            "processed": processed,
            "skipped": skipped
        }


    def process(self, session: Session, pay_run_id: int):

        pay_run = session.get(PayRun, pay_run_id)

        if pay_run is None:
            raise ValueError("Pay run not found")

        if pay_run.status != "draft":
            raise ValueError("Only draft pay runs can be processed")

        if pay_run.period_end < pay_run.period_start:
            raise ValueError("Pay period end cannot precede start")

        if pay_run.payment_date < pay_run.period_end:
            raise ValueError("Payment date cannot precede pay period end")

        if self._is_assignment_weekly(pay_run):
            return self._process_assignment_weekly(session, pay_run)

        # Retrieve all employees belonging to the organisation
        engagements = session.scalars(
            select(Engagement).where(
                Engagement.organisation_id == pay_run.organisation_id
            )
        ).all()

        processed = 0
        skipped = 0

        for engagement in engagements:

            # Check whether a payslip already exists
            existing = session.scalar(
                select(Payslip).where(
                    Payslip.pay_run_id == pay_run.id,
                    Payslip.engagement_id == engagement.id
                )
            )

            # Find the employee's work pattern
            agreement = session.scalar(
                select(WorkPattern).where(
                    WorkPattern.engagement_id == engagement.id,
                    WorkPattern.start_date <= pay_run.period_end,
                    (
                        WorkPattern.end_date.is_(None)
                        | (WorkPattern.end_date >= pay_run.period_start)
                    )
                ).order_by(
                    WorkPattern.start_date.desc()
                )
            )

            if agreement is None:
                skipped += 1
                continue

            # Retrieve approved timesheets within the pay period
            timesheets = session.scalars(
                select(Timesheet).where(
                    Timesheet.engagement_id == engagement.id,
                    Timesheet.work_date >= pay_run.period_start,
                    Timesheet.work_date <= pay_run.period_end,
                    Timesheet.status == "approved"
                )
            ).all()

            # Skip employees without approved timesheets
            if not timesheets:
                skipped += 1
                continue

            # Calculate actual hours worked
            hours_worked = sum(
                (timesheet.hours_worked for timesheet in timesheets),
                Decimal("0")
            )

            # Calculate payroll using approved timesheet hours
            result = PayrollEngine().calculate(
                session=session,
                agreement=agreement,
                payment_date=pay_run.payment_date,
                hours_worked=hours_worked,
                claims_tax_free_threshold=True
            )

            # Remove the existing draft payslip and its links
            # only after payroll calculation succeeds
            if existing:
                session.execute(
                    delete(PayslipTimesheet).where(
                        PayslipTimesheet.payslip_id == existing.id
                    )
                )

                session.delete(existing)
                session.flush()

            # Create the employee's updated payslip
            payslip = Payslip(
                engagement_id=engagement.id,
                pay_run_id=pay_run.id,
                
                gross_pay=result["gross_pay"],
                payg_withholding=result["payg_withholding"],
                net_pay=result["net_pay"],
                superannuation=result["superannuation"]
            )

            session.add(payslip)
            session.flush()

            # Link approved timesheets to the payslip
            for timesheet in timesheets:
                session.add(
                    PayslipTimesheet(
                        payslip_id=payslip.id,
                        timesheet_id=timesheet.id
                    )
                )

            processed += 1

        # Commit all payslips and timesheet links together
        session.commit()

        return {
            "processed": processed,
            "skipped": skipped
        }
