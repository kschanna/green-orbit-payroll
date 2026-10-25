from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)

    engagement_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id"),
        nullable=False
    )

    invoice_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False
    )

    issue_date: Mapped[date] = mapped_column(Date, nullable=False)

    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    pbt_schedule_period_id: Mapped[int | None] = mapped_column(
        ForeignKey("pbt_schedule_periods.id"), nullable=True, index=True
    )

    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    gst: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        default="draft",
        nullable=False
    )

    engagement = relationship("Assignment")
