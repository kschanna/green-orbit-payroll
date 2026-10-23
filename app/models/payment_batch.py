from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base
from app.models.user import User  # noqa: F401 - registers the referenced table


class PaymentBatch(Base):
    __tablename__ = "payment_batches"
    __table_args__ = (
        UniqueConstraint("pay_run_id", name="uq_payment_batch_pay_run"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False, index=True
    )
    pay_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pay_runs.id"), nullable=True, index=True
    )
    aba_profile_id: Mapped[int] = mapped_column(
        ForeignKey("aba_profiles.id"), nullable=False
    )
    processing_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    line_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
    )
    exported_at: Mapped[datetime | None] = mapped_column(DateTime)
    exported_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    file_checksum: Mapped[str | None] = mapped_column(String(64))
