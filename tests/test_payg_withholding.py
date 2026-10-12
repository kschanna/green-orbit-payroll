from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base
from app.models.payg_tax_table import PAYGTaxTable
from app.payroll.payg_withholding import PAYGWithholdingCalculator


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all([
            PAYGTaxTable(
                pay_frequency="fortnightly",
                claims_tax_free_threshold=True,
                gross_pay=Decimal("3400.00"),
                withholding_amount=Decimal("650.00"),
                effective_from=date(2026, 7, 1),
            ),
            PAYGTaxTable(
                pay_frequency="fortnightly",
                claims_tax_free_threshold=True,
                gross_pay=Decimal("3450.00"),
                withholding_amount=Decimal("665.00"),
                effective_from=date(2026, 7, 1),
            ),
        ])

        session.commit()
        yield session

    engine.dispose()


def test_nearest_lower_earnings(session):
    calculator = PAYGWithholdingCalculator()

    result = calculator.calculate(
        session=session,
        gross_pay=Decimal("3420.00"),
        pay_frequency="fortnightly",
        claims_tax_free_threshold=True,
        payment_date=date(2026, 10, 15),
    )

    assert result == Decimal("650.00")


def test_missing_tax_table(session):
    calculator = PAYGWithholdingCalculator()

    with pytest.raises(ValueError):
        calculator.calculate(
            session=session,
            gross_pay=Decimal("3420.00"),
            pay_frequency="monthly",
            claims_tax_free_threshold=True,
            payment_date=date(2026, 10, 15),
        )