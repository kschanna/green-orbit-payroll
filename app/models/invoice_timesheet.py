from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class InvoiceTimesheet(Base):
    __tablename__ = "invoice_timesheets"

    __table_args__ = (
        UniqueConstraint("timesheet_id", name="uq_invoice_timesheet"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id"),
        nullable=False
    )

    timesheet_id: Mapped[int] = mapped_column(
        ForeignKey("timesheets.id"),
        nullable=False
    )