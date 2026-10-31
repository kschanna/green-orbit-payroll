from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base
from app.models.user import User  # noqa: F401 - registers referenced table


class ABAFile(Base):
    __tablename__ = "aba_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_batch_id: Mapped[int] = mapped_column(
        ForeignKey("payment_batches.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    byte_size: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
