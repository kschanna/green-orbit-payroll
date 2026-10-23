from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class LeavePlan(Base):
    __tablename__ = "leave_plans"
    __table_args__ = (
        UniqueConstraint(
            "engagement_id", "component_definition_id", "effective_from",
            name="uq_leave_plan_effective_from",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    engagement_id: Mapped[int] = mapped_column(
        ForeignKey("engagements.id"), index=True
    )
    component_definition_id: Mapped[int] = mapped_column(
        ForeignKey("component_definitions.id"), index=True
    )
    annual_entitlement_hours: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False
    )
    standard_hours_per_year: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False
    )
    accrual_rate_per_hour: Mapped[Decimal] = mapped_column(
        Numeric(14, 10), nullable=False
    )
    plan_basis: Mapped[str] = mapped_column(
        String(30), nullable=False, default="statutory"
    )
    paid_leave_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    opening_balance_hours: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0")
    )
    allow_negative_balance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    accrues_during_paid_leave: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
