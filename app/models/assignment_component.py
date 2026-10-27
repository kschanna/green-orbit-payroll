from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class AssignmentComponent(Base):
    __tablename__ = "assignment_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id"), nullable=False
    )
    component_definition_id: Mapped[int] = mapped_column(
        ForeignKey("component_definitions.id"), nullable=False
    )
    rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    pay_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bill_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    applies_to: Mapped[str] = mapped_column(
        String(20), nullable=False, default="payroll"
    )
    processing_stage: Mapped[str] = mapped_column(
        String(30), nullable=False, default="earnings"
    )
    processing_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100
    )
    calculation_method: Mapped[str] = mapped_column(
        String(40), nullable=False, default="timesheet_rate"
    )
    unit_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="hours"
    )

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
