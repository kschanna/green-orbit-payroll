from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.payg_tax_table import PAYGTaxTable


def test_fy2025_26_regular_payg_tables_are_complete():
    with SessionLocal() as db:
        counts = dict(db.execute(
            select(
                PAYGTaxTable.pay_frequency,
                func.count(PAYGTaxTable.id),
            )
            .where(PAYGTaxTable.effective_from == date(2025, 7, 1))
            .group_by(PAYGTaxTable.pay_frequency)
        ).all())
        assert counts == {
            "weekly": 6800,
            "fortnightly": 6800,
            "monthly": 5760,
        }


def test_fy2025_26_weekly_1500_matches_ato_table():
    with SessionLocal() as db:
        amount = db.scalar(select(PAYGTaxTable.withholding_amount).where(
            PAYGTaxTable.pay_frequency == "weekly",
            PAYGTaxTable.claims_tax_free_threshold.is_(True),
            PAYGTaxTable.gross_pay == Decimal("1500.00"),
            PAYGTaxTable.effective_from == date(2025, 7, 1),
        ))
        assert amount == Decimal("304.00")
