from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class LeaveTransaction(Base):
    __tablename__ = "leave_transactions"
    __table_args__ = (
        UniqueConstraint(
            "leave_plan_id", "source_type", "source_id", "transaction_type",
            name="uq_leave_transaction_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    leave_plan_id: Mapped[int] = mapped_column(
        ForeignKey("leave_plans.id"), nullable=False, index=True
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
