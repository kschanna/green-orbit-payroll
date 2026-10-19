from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class EmployeeTaxProfile(Base):
    __tablename__ = "employee_tax_profiles"

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

    residency_status: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    claims_tax_free_threshold: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )
    has_study_loan: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    tfn_declaration_received: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
