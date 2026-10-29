from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.engagement import Engagement
from app.models.worker_document import WorkerDocument
from app.models.worker_form_submission import WorkerFormSubmission


PENDING_DOCUMENT_STATUSES = {"uploaded", "processing", "ready_for_review"}


def _current_document(db: Session, worker_id: int, document_type: str, as_of: date):
    return db.scalar(
        select(WorkerDocument).where(
            WorkerDocument.worker_id == worker_id,
            WorkerDocument.document_type == document_type,
            or_(
                WorkerDocument.expires_on.is_(None),
                WorkerDocument.expires_on >= as_of,
            ),
        ).order_by(WorkerDocument.created_at.desc(), WorkerDocument.id.desc()).limit(1)
    )


def payroll_setup_items(db: Session, worker_id: int, *, as_of: date | None = None) -> list[dict]:
    as_of = as_of or date.today()
    employee_engagement = db.scalar(select(Engagement.id).where(
        Engagement.worker_id == worker_id,
        Engagement.status == "active",
        Engagement.engagement_type.in_(("employee", "payg_employee")),
        or_(Engagement.start_date.is_(None), Engagement.start_date <= as_of),
        or_(Engagement.end_date.is_(None), Engagement.end_date >= as_of),
    ).limit(1))
    if employee_engagement is None:
        return []

    tax_document = _current_document(db, worker_id, "tfn_declaration", as_of)
    tax_form = db.scalar(select(WorkerFormSubmission).where(
        WorkerFormSubmission.worker_id == worker_id,
        WorkerFormSubmission.form_type == "tfn_declaration",
    ).order_by(WorkerFormSubmission.id.desc()).limit(1))
    tax_profile = db.scalar(select(EmployeeTaxProfile.id).where(
        EmployeeTaxProfile.worker_id == worker_id,
        EmployeeTaxProfile.tfn_declaration_received.is_(True),
        EmployeeTaxProfile.effective_from <= as_of,
        or_(EmployeeTaxProfile.effective_to.is_(None), EmployeeTaxProfile.effective_to >= as_of),
    ).limit(1))

    super_document = _current_document(db, worker_id, "super_choice", as_of)
    super_form = db.scalar(select(WorkerFormSubmission).where(
        WorkerFormSubmission.worker_id == worker_id,
        WorkerFormSubmission.form_type == "super_choice",
    ).order_by(WorkerFormSubmission.id.desc()).limit(1))
    super_profile = db.scalar(select(EmployeeSuperProfile).where(
        EmployeeSuperProfile.worker_id == worker_id,
        EmployeeSuperProfile.effective_from <= as_of,
        or_(EmployeeSuperProfile.effective_to.is_(None), EmployeeSuperProfile.effective_to >= as_of),
    ).limit(1))
    super_profile_complete = super_profile is not None and all((
        super_profile.fund_name,
        super_profile.fund_usi,
        super_profile.member_number,
    ))

    def status(document, form, profile_complete: bool) -> str:
        if form is not None and form.status == "approved" and profile_complete:
            return "complete"
        if form is not None and form.status == "submitted":
            return "pending"
        if document is not None and document.status == "approved" and profile_complete:
            return "complete"
        if document is not None and (
            document.status in PENDING_DOCUMENT_STATUSES or document.status == "approved"
        ):
            return "pending"
        return "missing"

    return [
        {
            "code": "tfn_declaration",
            "title": "TFN declaration",
            "status": status(tax_document, tax_form, tax_profile is not None),
            "action_url": "/portal/payroll-setup/tfn_declaration",
            "action_label": "Complete TFN declaration",
            "help": "Use the encrypted payroll form. Never send your TFN in chat or a message.",
        },
        {
            "code": "super_choice",
            "title": "Super choice form",
            "status": status(super_document, super_form, bool(super_profile_complete)),
            "action_url": "/portal/payroll-setup/super_choice",
            "action_label": "Complete super choice form",
            "help": "Complete the encrypted super choice form for payroll review.",
        },
    ]


def missing_payroll_setup_items(db: Session, worker_id: int, *, as_of: date | None = None) -> list[dict]:
    return [item for item in payroll_setup_items(db, worker_id, as_of=as_of) if item["status"] == "missing"]
