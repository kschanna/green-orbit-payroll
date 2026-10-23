from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base
from app.models.timesheet_header import TimesheetHeader


class Timesheet(Base):

    __tablename__ = "timesheets"

    engagement_id: Mapped[int | None] = mapped_column(
        ForeignKey("engagements.id"),
        index=True, nullable=True
    )


    __table_args__ = (
        CheckConstraint(
            "hours_worked >= 0 AND hours_worked <= 24",
            name="ck_timesheet_hours_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    employee_id: Mapped[int | None] = mapped_column(
        
        nullable=True
    )

    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id"),
        nullable=True
    )

    component_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("component_definitions.id"),
        nullable=True,
    )

    leave_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("leave_plans.id"), nullable=True, index=True
    )

    # Links daily entries to a timesheet header.
    # Nullable to preserve existing timesheets.
    timesheet_header_id: Mapped[int | None] = mapped_column(
        ForeignKey("timesheet_headers.id"),
        nullable=True
    )

    work_date: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    hours_worked: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="draft",
        nullable=False
    )


    header: Mapped["TimesheetHeader | None"] = relationship(
        "TimesheetHeader",
        back_populates="timesheets"
    )
