from decimal import Decimal, ROUND_HALF_UP


class SuperannuationCalculator:

    def calculate(
        self,
        ordinary_time_earnings: Decimal,
        rate: Decimal = Decimal("0.12")
    ) -> Decimal:

        if ordinary_time_earnings < 0:
            raise ValueError("Earnings cannot be negative")

        return (
            ordinary_time_earnings * rate
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )