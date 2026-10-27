from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("worker_documents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    processor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    proposed_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
