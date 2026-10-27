from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class InvoiceComponentAllocation(Base):
    __tablename__ = "invoice_component_allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_component_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_components.id", ondelete="CASCADE"), nullable=False
    )
    source_invoice_component_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_components.id", ondelete="CASCADE"), nullable=False
    )
    basis: Mapped[str] = mapped_column(String(20), nullable=False)
    source_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    source_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
