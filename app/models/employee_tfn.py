from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class EmployeeTFN(Base):
    __tablename__ = "employee_tfns"

    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.id"),
        primary_key=True,
        nullable=False,
    )

    engagement_id: Mapped[int | None] = mapped_column(
        ForeignKey("engagements.id"),
        nullable=True,
        index=True,
    )


    employee_id: Mapped[int | None] = mapped_column(
        
        nullable=True,
    )

    encrypted_tfn: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )

    last_three: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
