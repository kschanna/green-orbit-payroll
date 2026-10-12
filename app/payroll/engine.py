from decimal import Decimal

from app.payroll.gross_pay import GrossPayCalculator
from app.payroll.payg_withholding import PAYGWithholdingCalculator
from app.payroll.superannuation import SuperannuationCalculator


class PayrollEngine:

    def calculate(
        self,
        session,
        agreement,
        payment_date,
        hours_worked,
        claims_tax_free_threshold=True
    ):

        gross_pay = GrossPayCalculator().calculate(
            hours_worked=hours_worked,
            hourly_rate=agreement.hourly_rate
        )

        payg = PAYGWithholdingCalculator().calculate(
            session=session,
            gross_pay=gross_pay,
            pay_frequency=agreement.pay_frequency,
            claims_tax_free_threshold=claims_tax_free_threshold,
            payment_date=payment_date
        )

        superannuation = SuperannuationCalculator().calculate(
            ordinary_time_earnings=gross_pay
        )

        net_pay = gross_pay - payg

        return {
            "gross_pay": gross_pay,
            "payg_withholding": payg,
            "net_pay": net_pay,
            "superannuation": superannuation
        }