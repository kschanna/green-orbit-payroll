from sqlalchemy import select, func

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.pay_run import PayRun
from app.models.payslip import Payslip


def main():
    with SessionLocal() as session:

        pay_run = session.get(PayRun, 1)

        if pay_run is None:
            raise ValueError("Pay run not found")

        print(f"\nGREEN ORBIT — PAY RUN #{pay_run.id}")
        print(f"Period: {pay_run.period_start} to {pay_run.period_end}")
        print(f"Payment date: {pay_run.payment_date}")
        print(f"Status: {pay_run.status.upper()}")
        print("-" * 65)

        statement = (
            select(Payslip, Employee)
            .join(Employee, Payslip.employee_id == Employee.id)
            .where(Payslip.pay_run_id == pay_run.id)
            .order_by(Employee.id)
        )

        rows = session.execute(statement).all()

        for payslip, employee in rows:
            print(f"\n{employee.first_name} {employee.last_name}")
            print(f"  Gross Pay:  ${payslip.gross_pay:,.2f}")
            print(f"  PAYG:       ${payslip.payg_withholding:,.2f}")
            print(f"  Net Pay:    ${payslip.net_pay:,.2f}")
            print(f"  Super:      ${payslip.superannuation:,.2f}")

        totals = session.execute(
            select(
                func.count(Payslip.id),
                func.sum(Payslip.gross_pay),
                func.sum(Payslip.payg_withholding),
                func.sum(Payslip.net_pay),
                func.sum(Payslip.superannuation)
            ).where(Payslip.pay_run_id == pay_run.id)
        ).one()

        count, gross, payg, net, super_amount = totals

        gross = gross or 0
        payg = payg or 0
        net = net or 0
        super_amount = super_amount or 0

        print("\n" + "=" * 65)
        print("PAY RUN TOTALS")
        print(f"Employees paid:      {count}")
        print(f"Total Gross:        ${gross:,.2f}")
        print(f"Total PAYG:         ${payg:,.2f}")
        print(f"Total Net:          ${net:,.2f}")
        print(f"Total Super:        ${super_amount:,.2f}")
        print(f"Total Employer Cost: ${gross + super_amount:,.2f}")
        print("=" * 65)


if __name__ == "__main__":
    main()