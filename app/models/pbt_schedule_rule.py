from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class PBTScheduleRule(Base):
    __tablename__ = "pbt_schedule_rules"
    __table_args__ = (
        UniqueConstraint(
            "pbt_schedule_id",
            "schedule_type",
            name="uq_pbt_schedule_rule_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pbt_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("pbt_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    anchor_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    offset_days: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_payment_terms_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    active: Mapped[bool] = mapped_column(nullable=False, default=True)

    schedule = relationship("PBTSchedule", back_populates="rules")
    periods = relationship(
        "PBTSchedulePeriod",
        back_populates="rule",
        cascade="all, delete-orphan",
    )
