from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(primary_key=True)

    first_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    last_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    email: Mapped[str] = mapped_column(
        String(200), nullable=False
    )

    phone: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
