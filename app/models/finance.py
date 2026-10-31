from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class GLAccount(Base):
    __tablename__ = "gl_accounts"
    __table_args__ = (
        UniqueConstraint("code", name="uq_gl_account_code"),
        UniqueConstraint("role", name="uq_gl_account_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ComponentGLMapping(Base):
    __tablename__ = "component_gl_mappings"
    __table_args__ = (
        UniqueConstraint(
            "component_definition_id", "context",
            name="uq_component_gl_mapping_context",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    component_definition_id: Mapped[int] = mapped_column(
        ForeignKey("component_definitions.id"), nullable=False, index=True
    )
    context: Mapped[str] = mapped_column(String(30), nullable=False)
    gl_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=True
    )
    debit_gl_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=True
    )
    credit_gl_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=True
    )


class FinancePosting(Base):
    __tablename__ = "finance_postings"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_finance_posting_source"),
        CheckConstraint("total_debits >= 0", name="ck_finance_posting_debits_nonnegative"),
        CheckConstraint("total_credits >= 0", name="ck_finance_posting_credits_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(nullable=False)
    source_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(250), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted")
    total_debits: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_credits: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    source_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    balanced: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reconciled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class FinancePostingLine(Base):
    __tablename__ = "finance_posting_lines"
    __table_args__ = (
        CheckConstraint("debit >= 0", name="ck_finance_line_debit_nonnegative"),
        CheckConstraint("credit >= 0", name="ck_finance_line_credit_nonnegative"),
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="ck_finance_line_one_side",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(
        ForeignKey("finance_postings.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    gl_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=True
    )
    account_code: Mapped[str] = mapped_column(String(30), nullable=False)
    account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(250), nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    component_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("component_definitions.id"), nullable=True
    )
    component_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_line_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_line_id: Mapped[int | None] = mapped_column(nullable=True)
