from decimal import Decimal

from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base
from app.models.pbt_schedule import PBTSchedule  # noqa: F401


class Assignment(Base):
    __tablename__ = "assignments"

    engagement_id: Mapped[int] = mapped_column(
        ForeignKey("engagements.id"),
        nullable=False,
        index=True,
    )

    engagement = relationship("Engagement")


    id: Mapped[int] = mapped_column(primary_key=True)

    employee_id: Mapped[int | None] = mapped_column(
        
        nullable=True
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"),
        nullable=False
    )

    pbt_schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("pbt_schedules.id"),
        nullable=True,
        index=True,
    )

    host_organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id"),
        nullable=True,
        index=True,
    )

    billing_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False
    )

    start_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    end_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )


    customer = relationship("Organisation", foreign_keys=[customer_id])
    host_organisation = relationship(
        "Organisation",
        foreign_keys=[host_organisation_id],
    )
    pbt_schedule = relationship("PBTSchedule")
