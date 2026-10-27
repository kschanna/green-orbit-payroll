from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class WorkerDocument(Base):
    __tablename__ = "worker_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    uploaded_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), index=True, nullable=False, default="uploaded"
    )
    issued_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
