from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class Engagement(Base):
    __tablename__ = "engagements"

    id: Mapped[int] = mapped_column(primary_key=True)

    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.id"), nullable=False
    )

    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False
    )

    engagement_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )

    start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )

    end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )

    worker = relationship("Worker")
    organisation = relationship("Organisation")
