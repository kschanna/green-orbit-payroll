from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base
from app.models.timesheet_header import TimesheetHeader


class Timesheet(Base):

    __tablename__ = "timesheets"

    __table_args__ = (
        CheckConstraint(
            "hours_worked >= 0 AND hours_worked <= 24",
            name="ck_timesheet_hours_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"),
        nullable=False
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

    employee: Mapped["Employee"] = relationship()

    header: Mapped["TimesheetHeader | None"] = relationship(
        "TimesheetHeader",
        back_populates="timesheets"
    )