from decimal import Decimal

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.employment_agreement import EmploymentAgreement
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.timesheet import Timesheet
from app.models.payslip_timesheet import PayslipTimesheet

from app.payroll.engine import PayrollEngine


class PayRunProcessor:

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

        # Retrieve all employees belonging to the organisation
        employees = session.scalars(
            select(Employee).where(
                Employee.organisation_id == pay_run.organisation_id
            )
        ).all()

        processed = 0
        skipped = 0

        for employee in employees:

            # Check whether a payslip already exists
            existing = session.scalar(
                select(Payslip).where(
                    Payslip.pay_run_id == pay_run.id,
                    Payslip.employee_id == employee.id
                )
            )

            # Find the employee's employment agreement
            agreement = session.scalar(
                select(EmploymentAgreement).where(
                    EmploymentAgreement.employee_id == employee.id,
                    EmploymentAgreement.start_date <= pay_run.period_end,
                    (
                        EmploymentAgreement.end_date.is_(None)
                        | (EmploymentAgreement.end_date >= pay_run.period_start)
                    )
                ).order_by(
                    EmploymentAgreement.start_date.desc()
                )
            )

            if agreement is None:
                skipped += 1
                continue

            # Retrieve approved timesheets within the pay period
            timesheets = session.scalars(
                select(Timesheet).where(
                    Timesheet.employee_id == employee.id,
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
                pay_run_id=pay_run.id,
                employee_id=employee.id,
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