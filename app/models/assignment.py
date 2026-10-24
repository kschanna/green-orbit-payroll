from decimal import Decimal

from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class Assignment(Base):
    __tablename__ = "assignments"

    engagement_id: Mapped[int] = mapped_column(
        ForeignKey("engagements.id"),
        nullable=False,
        index=True,
    )

    engagement = relationship("Engagement")


    id: Mapped[int] = mapped_column(primary_key=True)

    employee_id: Mapped[int | None] = mapped_column(
        
        nullable=True
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"),
        nullable=False
    )

    billing_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False
    )

    start_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    end_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )


    customer = relationship("Organisation")
