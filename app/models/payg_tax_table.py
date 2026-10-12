from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class PAYGTaxTable(Base):

    __tablename__ = "payg_tax_tables"

    __table_args__ = (
        UniqueConstraint(
            "pay_frequency",
            "claims_tax_free_threshold",
            "gross_pay",
            "effective_from",
            name="uq_payg_tax_table_entry"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    pay_frequency: Mapped[str] = mapped_column(
        String(20), nullable=False
    )

    claims_tax_free_threshold: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )

    gross_pay: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )

    withholding_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )

    effective_from: Mapped[date] = mapped_column(
        Date, nullable=False
    )

    effective_to: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )