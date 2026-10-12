from decimal import Decimal


class GrossPayCalculator:

    def calculate(self, hours_worked: Decimal, hourly_rate: Decimal) -> Decimal:

        if hours_worked < 0:
            raise ValueError("Hours worked cannot be negative")

        if hourly_rate < 0:
            raise ValueError("Hourly rate cannot be negative")

        gross_pay = hours_worked * hourly_rate

        return gross_pay