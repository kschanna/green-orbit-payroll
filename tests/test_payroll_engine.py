from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.payroll.engine import PayrollEngine


def test_payroll_engine():

    agreement = SimpleNamespace(
        hourly_rate=Decimal("45.00"),
        pay_frequency="fortnightly"
    )

    with patch(
        "app.payroll.engine.PAYGWithholdingCalculator.calculate",
        return_value=Decimal("732.00")
    ):

        result = PayrollEngine().calculate(
            session=None,
            agreement=agreement,
            payment_date=date(2026, 10, 15),
            hours_worked=Decimal("76.00")
        )

    assert result["gross_pay"] == Decimal("3420.00")
    assert result["payg_withholding"] == Decimal("732.00")
    assert result["net_pay"] == Decimal("2688.00")
    assert result["superannuation"] == Decimal("410.40")