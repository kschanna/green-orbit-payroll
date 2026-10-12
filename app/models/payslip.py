from decimal import Decimal

# from sqlalchemy import ForeignKey, Numeric
from sqlalchemy import ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class Payslip(Base):

    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint(
            "pay_run_id",
            "employee_id",
            name="uq_payslip_pay_run_employee"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    pay_run_id: Mapped[int] = mapped_column(
        ForeignKey("pay_runs.id"),
        nullable=False
    )

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"),
        nullable=False
    )

    gross_pay: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )

    payg_withholding: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )

    net_pay: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )

    superannuation: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )

    pay_run = relationship("PayRun")
    employee = relationship("Employee")