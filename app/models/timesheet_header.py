from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class TimesheetHeader(Base):

    __tablename__ = "timesheet_headers"

    id: Mapped[int] = mapped_column(primary_key=True)

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"),
        nullable=False
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

    employee = relationship("Employee")

    timesheets = relationship(
        "Timesheet",
        back_populates="header"
    )