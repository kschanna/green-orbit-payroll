from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base
from app.models.employee import Employee


class EmploymentAgreement(Base):

    __tablename__ = "employment_agreements"

    id: Mapped[int] = mapped_column(primary_key=True)

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"),
        nullable=False
    )

    employment_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )

    pay_basis: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )

    hourly_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False
    )

    ordinary_hours_per_week: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False
    )

    pay_frequency: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )

    start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    end_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True
    )

    employee: Mapped["Employee"] = relationship()