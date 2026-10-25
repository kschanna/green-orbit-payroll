from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class TimesheetHeader(Base):

    __tablename__ = "timesheet_headers"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "pbt_schedule_period_id",
            name="uq_timesheet_header_assignment_pbt_period",
        ),
    )

    engagement_id: Mapped[int | None] = mapped_column(
        ForeignKey("engagements.id"),
        index=True, nullable=True
    )

    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id"), index=True, nullable=True
    )

    pbt_schedule_period_id: Mapped[int | None] = mapped_column(
        ForeignKey("pbt_schedule_periods.id"), index=True, nullable=True
    )


    id: Mapped[int] = mapped_column(primary_key=True)

    employee_id: Mapped[int | None] = mapped_column(
        
        nullable=True
    )

    period_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )

    period_start: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    period_end: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="draft",
        nullable=False
    )

    source: Mapped[str] = mapped_column(
        String(20), default="manual", nullable=False
    )


    timesheets = relationship(
        "Timesheet",
        back_populates="header"
    )
