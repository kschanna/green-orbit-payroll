from datetime import date, datetime

from sqlalchemy import (
    Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class PBTSchedulePeriod(Base):
    __tablename__ = "pbt_schedule_periods"
    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "period_start",
            "period_end",
            name="uq_pbt_rule_period",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pbt_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("pbt_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("pbt_schedule_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payment_terms_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    customer_payment_due_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planned"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    schedule = relationship("PBTSchedule", back_populates="periods")
    rule = relationship("PBTScheduleRule", back_populates="periods")
