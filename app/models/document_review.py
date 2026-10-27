from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class DocumentReview(Base):
    __tablename__ = "document_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("worker_documents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    reviewer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    decision: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )
    corrected_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
