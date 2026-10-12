from decimal import Decimal

import pytest

from app.payroll.superannuation import SuperannuationCalculator


def test_superannuation_calculation():
    calculator = SuperannuationCalculator()

    result = calculator.calculate(
        ordinary_time_earnings=Decimal("3420.00")
    )

    assert result == Decimal("410.40")


def test_zero_earnings():
    calculator = SuperannuationCalculator()

    result = calculator.calculate(
        ordinary_time_earnings=Decimal("0.00")
    )

    assert result == Decimal("0.00")


def test_negative_earnings():
    calculator = SuperannuationCalculator()

    with pytest.raises(ValueError):
        calculator.calculate(
            ordinary_time_earnings=Decimal("-100.00")
        )


def test_custom_super_rate():
    calculator = SuperannuationCalculator()

    result = calculator.calculate(
        ordinary_time_earnings=Decimal("1000.00"),
        rate=Decimal("0.15")
    )

    assert result == Decimal("150.00")