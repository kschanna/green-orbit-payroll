import pytest
from decimal import Decimal
from app.payroll.gross_pay import GrossPayCalculator

def test_calculate_gross_pay():
    calculator = GrossPayCalculator()
    hours = Decimal("38")
    rate = Decimal("45.00")
    result = calculator.calculate(hours, rate)
    assert result == Decimal("1710.00")

def test_negative_hours():
    calculator = GrossPayCalculator()
    hours = Decimal("-38")
    rate = Decimal("45.00")
    with pytest.raises(ValueError):
        calculator.calculate(hours, rate)

def test_negative_hourly_rate():
    calculator = GrossPayCalculator()
    hours = Decimal("38")
    rate = Decimal("-45.00")
    with pytest.raises(ValueError):
        calculator.calculate(hours, rate)