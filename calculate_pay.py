from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models.employment_agreement import EmploymentAgreement
from app.payroll.gross_pay import GrossPayCalculator
from app.payroll.payg_withholding import PAYGWithholdingCalculator
from app.payroll.superannuation import SuperannuationCalculator


def main():
    with SessionLocal() as session:

        agreement = session.scalar(
            select(EmploymentAgreement)
            .where(EmploymentAgreement.employee_id == 1)
        )

        if agreement is None:
            print("Employment agreement not found")
            return

        hours = agreement.ordinary_hours_per_week * Decimal("2")

        gross_pay = GrossPayCalculator().calculate(
            hours_worked=hours,
            hourly_rate=agreement.hourly_rate
        )

        payg = PAYGWithholdingCalculator().calculate(
            session=session,
            gross_pay=gross_pay,
            pay_frequency=agreement.pay_frequency,
            claims_tax_free_threshold=True,
            payment_date=date(2026, 10, 15)
        )

        net_pay = gross_pay - payg
        superannuation = SuperannuationCalculator().calculate(
            ordinary_time_earnings=gross_pay
        )

        total_employer_cost = gross_pay + superannuation

        print("\nGREEN ORBIT PAYROLL")
        print("-------------------------")
        print(f"Gross Pay:  ${gross_pay:.2f}")
        print(f"PAYG Tax:   ${payg:.2f}")
        print(f"Net Pay:    ${net_pay:.2f}")
        print(f"Super:      ${superannuation:.2f}")
        print(f"Employer Cost: ${total_employer_cost:.2f}")


if __name__ == "__main__":
    main()