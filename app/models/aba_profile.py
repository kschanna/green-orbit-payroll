from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class ABAProfile(Base):
    __tablename__ = "aba_profiles"
    __table_args__ = (
        UniqueConstraint("organisation_id", name="uq_aba_profile_organisation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False, index=True
    )
    financial_institution: Mapped[str] = mapped_column(String(3), nullable=False)
    user_name: Mapped[str] = mapped_column(String(26), nullable=False)
    apca_user_id: Mapped[str] = mapped_column(String(6), nullable=False)
    file_description: Mapped[str] = mapped_column(
        String(12), nullable=False, default="PAYROLL"
    )
    source_bsb: Mapped[str] = mapped_column(String(6), nullable=False)
    source_account_number: Mapped[str] = mapped_column(String(9), nullable=False)
    source_account_name: Mapped[str] = mapped_column(String(32), nullable=False)
    remitter_name: Mapped[str] = mapped_column(String(16), nullable=False)
    transaction_code: Mapped[str] = mapped_column(
        String(2), nullable=False, default="53"
    )
    balancing_entry_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
