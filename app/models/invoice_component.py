from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class InvoiceComponent(Base):
    __tablename__ = "invoice_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id"), nullable=False
    )
    component_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("component_definitions.id"), nullable=True
    )
    assignment_component_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignment_components.id"), nullable=True
    )
    component_code: Mapped[str | None] = mapped_column(String(50))
    component_name: Mapped[str | None] = mapped_column(String(150))
    family_code: Mapped[str | None] = mapped_column(String(50))
    calculation_method: Mapped[str | None] = mapped_column(String(40))
    unit_type: Mapped[str | None] = mapped_column(String(20))
    base_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    processing_order: Mapped[int | None] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
