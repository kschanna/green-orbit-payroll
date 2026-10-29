from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class WorkerFormSubmission(Base):
    __tablename__ = "worker_form_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), index=True)
    submitted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    form_type: Mapped[str] = mapped_column(String(50), index=True)
    schema_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), index=True, default="submitted")
    submission_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    declaration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
