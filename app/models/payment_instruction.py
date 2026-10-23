from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class PaymentInstruction(Base):
    __tablename__ = "payment_instructions"
    __table_args__ = (
        UniqueConstraint(
            "payment_batch_id", "payslip_id",
            name="uq_payment_instruction_batch_payslip",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_batch_id: Mapped[int] = mapped_column(
        ForeignKey("payment_batches.id"), nullable=False, index=True
    )
    payslip_id: Mapped[int | None] = mapped_column(
        ForeignKey("payslips.id"), nullable=True, index=True
    )
    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.id"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    recipient_account_name: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_bsb: Mapped[str] = mapped_column(String(6), nullable=False)
    recipient_account_number: Mapped[str] = mapped_column(String(9), nullable=False)
    transaction_code: Mapped[str] = mapped_column(String(2), nullable=False)
    lodgement_reference: Mapped[str] = mapped_column(String(18), nullable=False)
    trace_bsb: Mapped[str] = mapped_column(String(6), nullable=False)
    trace_account_number: Mapped[str] = mapped_column(String(9), nullable=False)
    remitter_name: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    manual_entry_reason: Mapped[str | None] = mapped_column(String(250))
