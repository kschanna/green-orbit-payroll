from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class User(Base):

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    email: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )

    role: Mapped[str] = mapped_column(
        String(20), default="admin", nullable=False
    )

    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
    )

    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
