from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.organisation import Base


class Employee(Base):

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)

    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"),
        nullable=False
    )

    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    email: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )

    organisation: Mapped["Organisation"] = relationship()