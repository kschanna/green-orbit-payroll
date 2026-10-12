from decimal import Decimal

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.employment_agreement import EmploymentAgreement
from app.models.pay_run import PayRun
from app.models.payslip import Payslip

from app.payroll.engine import PayrollEngine


def main():

    with SessionLocal() as session:

        # Retrieve the pay run and employee
        pay_run = session.get(PayRun, 1)
        employee = session.get(Employee, 1)

        if pay_run is None:
            raise ValueError("Pay run not found")

        if employee is None:
            raise ValueError("Employee not found")

        # Retrieve the employee's employment agreement
        agreement = (
            session.query(EmploymentAgreement)
            .filter_by(employee_id=employee.id)
            .first()
        )

        if agreement is None:
            raise ValueError("Employment agreement not found")

        # Prevent duplicate payslips
        existing_payslip = (
            session.query(Payslip)
            .filter_by(
                pay_run_id=pay_run.id,
                employee_id=employee.id
            )
            .first()
        )

        if existing_payslip:
            print(
                f"Payslip already exists for "
                f"{employee.first_name} {employee.last_name}"
            )
            print(f"Payslip ID: {existing_payslip.id}")
            return

        # Calculate fortnightly ordinary hours
        hours_worked = (
            agreement.ordinary_hours_per_week * Decimal("2")
        )

        # Calculate payroll using our PayrollEngine
        result = PayrollEngine().calculate(
            session=session,
            agreement=agreement,
            payment_date=pay_run.payment_date,
            hours_worked=hours_worked,
            claims_tax_free_threshold=True
        )

        # Create the payslip
        payslip = Payslip(
            pay_run_id=pay_run.id,
            employee_id=employee.id,
            gross_pay=result["gross_pay"],
            payg_withholding=result["payg_withholding"],
            net_pay=result["net_pay"],
            superannuation=result["superannuation"]
        )

        # Save to PostgreSQL
        session.add(payslip)
        session.commit()

        # Display results
        print(f"Payslip created: {payslip.id}")
        print(
            f"Employee: {employee.first_name} "
            f"{employee.last_name}"
        )
        print(f"Gross Pay: ${result['gross_pay']:.2f}")
        print(f"PAYG: ${result['payg_withholding']:.2f}")
        print(f"Net Pay: ${result['net_pay']:.2f}")
        print(f"Superannuation: ${result['superannuation']:.2f}")


if __name__ == "__main__":
    main()