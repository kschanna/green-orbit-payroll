from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class TimesheetHeader(Base):

    __tablename__ = "timesheet_headers"

    engagement_id: Mapped[int | None] = mapped_column(
        ForeignKey("engagements.id"),
        index=True, nullable=True
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


    timesheets = relationship(
        "Timesheet",
        back_populates="header"
    )