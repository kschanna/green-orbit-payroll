from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class PayrollAgentStep(Base):
    __tablename__ = "payroll_agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_payroll_agent_run_step"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_agent_runs.id", ondelete="CASCADE"), index=True
    )
    step_key: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(160))
    sequence: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(30), index=True)
    decision_source: Mapped[str] = mapped_column(String(30), default="deterministic")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
