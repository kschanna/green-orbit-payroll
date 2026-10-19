from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
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


    customer = relationship("Organisation")