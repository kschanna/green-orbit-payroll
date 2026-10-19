from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class EmployeePaymentDetail(Base):
    __tablename__ = "employee_payment_details"

    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.id"), nullable=False
    )

    engagement_id: Mapped[int | None] = mapped_column(
        ForeignKey("engagements.id"),
        index=True,
        nullable=True,
    )


    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int | None] = mapped_column(
         nullable=True
    )

    payment_method: Mapped[str] = mapped_column(
        String(30), nullable=False, default="bank_transfer"
    )

    # Bank account details will be added after encryption is implemented.

    account_name: Mapped[str | None] = mapped_column(String(200))
    bsb: Mapped[str | None] = mapped_column(String(6))
    account_number: Mapped[str | None] = mapped_column(String(20))

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
