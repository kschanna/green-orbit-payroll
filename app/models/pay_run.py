from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class PayRun(Base):

    __tablename__ = "pay_runs"

    id: Mapped[int] = mapped_column(primary_key=True)

    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"),
        nullable=False
    )

    period_start: Mapped[date] = mapped_column(
        Date, nullable=False
    )

    period_end: Mapped[date] = mapped_column(
        Date, nullable=False
    )

    payment_date: Mapped[date] = mapped_column(
        Date, nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft"
    )

    organisation = relationship("Organisation")