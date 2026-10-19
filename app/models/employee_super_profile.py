from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class EmployeeSuperProfile(Base):
    __tablename__ = "employee_super_profiles"

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

    fund_name: Mapped[str | None] = mapped_column(String(200))
    fund_usi: Mapped[str | None] = mapped_column(String(50))
    member_number: Mapped[str | None] = mapped_column(String(100))

    additional_employer_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4)
    )

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
