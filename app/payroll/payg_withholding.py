from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payg_tax_table import PAYGTaxTable


class PAYGWithholdingCalculator:

    def calculate(
        self,
        session: Session,
        gross_pay: Decimal,
        pay_frequency: str,
        claims_tax_free_threshold: bool,
        payment_date: date
    ) -> Decimal:

        if gross_pay < 0:
            raise ValueError("Gross pay cannot be negative")

        if pay_frequency not in ("weekly", "fortnightly", "monthly"):
            raise ValueError("Unsupported pay frequency")

        statement = (
            select(PAYGTaxTable)
            .where(
                PAYGTaxTable.pay_frequency == pay_frequency,
                PAYGTaxTable.claims_tax_free_threshold == claims_tax_free_threshold,
                PAYGTaxTable.effective_from <= payment_date,
                (PAYGTaxTable.effective_to.is_(None)) |
                (PAYGTaxTable.effective_to >= payment_date),
                PAYGTaxTable.gross_pay <= gross_pay
            )
            .order_by(
                PAYGTaxTable.gross_pay.desc(),
                PAYGTaxTable.effective_from.desc()
            )
            .limit(1)
        )

        tax_row = session.scalar(statement)

        if tax_row is None:
            raise ValueError("No applicable PAYG withholding table entry found")

        return tax_row.withholding_amount