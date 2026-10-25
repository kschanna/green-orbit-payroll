from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class PBTSchedule(Base):
    __tablename__ = "pbt_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )
    generation_months: Mapped[int] = mapped_column(
        Integer, nullable=False, default=12
    )
    generated_through: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now()
    )

    customer = relationship("Organisation")
    rules = relationship(
        "PBTScheduleRule",
        back_populates="schedule",
        cascade="all, delete-orphan",
    )
    periods = relationship(
        "PBTSchedulePeriod",
        back_populates="schedule",
        cascade="all, delete-orphan",
    )


# Register the related tables whenever the aggregate root is imported.
from app.models.pbt_schedule_rule import PBTScheduleRule  # noqa: E402,F401
from app.models.pbt_schedule_period import PBTSchedulePeriod  # noqa: E402,F401
