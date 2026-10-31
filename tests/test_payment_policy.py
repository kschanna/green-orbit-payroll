from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.payroll.payment_policy import (
    CompanyContractorPaymentPolicy,
    PAYGContractorPaymentPolicy,
    PAYGEmployeePaymentPolicy,
    payment_policy_for,
    supports_payment_policy,
)


def test_payment_policy_factory_uses_engagement_specific_classes():
    assert isinstance(payment_policy_for("payg_employee"), PAYGEmployeePaymentPolicy)
    assert isinstance(payment_policy_for("payg_contractor"), PAYGContractorPaymentPolicy)
    assert isinstance(
        payment_policy_for("company_contractor"),
        CompanyContractorPaymentPolicy,
    )
    assert supports_payment_policy("company_contractor") is True
    assert supports_payment_policy("unsupported") is False


def test_company_contractor_deducts_components_then_adds_gst():
    fixed = SimpleNamespace(
        pay_rate=Decimal("25.00"), processing_order=200, id=2
    )
    fixed_definition = SimpleNamespace(
        id=12, name="Administration Deduction", calculation_type="fixed"
    )
    percentage = SimpleNamespace(
        pay_rate=Decimal("5.00"), processing_order=201, id=3
    )
    percentage_definition = SimpleNamespace(
        id=13, name="Service Deduction", calculation_type="percentage"
    )
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        (fixed, fixed_definition),
        (percentage, percentage_definition),
    ]
    entries = [
        SimpleNamespace(work_date=date(2026, 10, 1), hours_worked=Decimal("8")),
        SimpleNamespace(work_date=date(2026, 10, 2), hours_worked=Decimal("8")),
    ]

    result = CompanyContractorPaymentPolicy().calculate(
        session=session,
        assignment=SimpleNamespace(id=99),
        engagement=SimpleNamespace(id=88),
        entries=entries,
        gross=Decimal("1000.00"),
        payment_date=date(2026, 10, 3),
        pay_frequency="weekly",
    )

    assert result.deductions_total == Decimal("75.00")
    assert result.net_before_gst == Decimal("925.00")
    assert result.gst_paid == Decimal("92.50")
    assert result.payment_total == Decimal("1017.50")
    assert [line["amount"] for line in result.component_lines] == [
        Decimal("25.00"), Decimal("50.00")
    ]


def test_company_contractor_rejects_deductions_over_earnings():
    component = SimpleNamespace(
        pay_rate=Decimal("120.00"), processing_order=200, id=2
    )
    definition = SimpleNamespace(
        id=12, name="Deduction", calculation_type="fixed"
    )
    session = MagicMock()
    session.execute.return_value.all.return_value = [(component, definition)]

    with pytest.raises(ValueError, match="deductions exceed earnings"):
        CompanyContractorPaymentPolicy().calculate(
            session=session,
            assignment=SimpleNamespace(id=99),
            engagement=SimpleNamespace(id=88),
            entries=[SimpleNamespace(
                work_date=date(2026, 10, 1), hours_worked=Decimal("1")
            )],
            gross=Decimal("100.00"),
            payment_date=date(2026, 10, 2),
            pay_frequency="weekly",
        )
