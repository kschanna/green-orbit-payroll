from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class PayrollAgentRun(Base):
    __tablename__ = "payroll_agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    pbt_schedule_period_id: Mapped[int] = mapped_column(
        ForeignKey("pbt_schedule_periods.id"), index=True
    )
    triggered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(40), index=True)
    current_step: Mapped[str] = mapped_column(String(80))
    blockers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    records: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
