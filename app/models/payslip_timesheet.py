from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class PayslipTimesheet(Base):

    __tablename__ = "payslip_timesheets"

    __table_args__ = (
        UniqueConstraint(
            "payslip_id",
            "timesheet_id",
            name="uq_payslip_timesheet"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    payslip_id: Mapped[int] = mapped_column(
        ForeignKey("payslips.id"),
        nullable=False
    )

    timesheet_id: Mapped[int] = mapped_column(
        ForeignKey("timesheets.id"),
        nullable=False
    )

    payslip = relationship("Payslip")
    timesheet = relationship("Timesheet")