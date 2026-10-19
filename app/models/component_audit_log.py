from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class ComponentAuditLog(Base):
    __tablename__ = "component_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("component_definitions.id")
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
