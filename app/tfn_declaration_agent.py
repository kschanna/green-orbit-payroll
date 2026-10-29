"""Event check used by the assistant after a timesheet is created."""

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.engagement import Engagement
from app.models.worker import Worker
from app.models.worker_document import WorkerDocument


def missing_tfn_declaration_alert(
    db: Session, engagement_id: int, *, as_of: date
) -> dict | None:
    engagement = db.get(Engagement, engagement_id)
    if engagement is None or engagement.engagement_type not in {
        "employee", "payg_employee"
    }:
        return None
    worker = db.get(Worker, engagement.worker_id)
    declaration = db.scalar(
        select(EmployeeTaxProfile).where(
            EmployeeTaxProfile.worker_id == engagement.worker_id,
            EmployeeTaxProfile.tfn_declaration_received.is_(True),
            EmployeeTaxProfile.effective_from <= as_of,
            or_(
                EmployeeTaxProfile.effective_to.is_(None),
                EmployeeTaxProfile.effective_to >= as_of,
            ),
        ).limit(1)
    )
    document = db.scalar(
        select(WorkerDocument).where(
            WorkerDocument.worker_id == engagement.worker_id,
            WorkerDocument.document_type == "tfn_declaration",
            WorkerDocument.status == "approved",
            or_(
                WorkerDocument.expires_on.is_(None),
                WorkerDocument.expires_on >= as_of,
            ),
        ).limit(1)
    )
    if declaration is not None and document is not None:
        return None
    worker_name = (
        f"{worker.first_name} {worker.last_name}" if worker else "This worker"
    )
    return {
        "code": "missing_tfn_declaration",
        "severity": "critical",
        "content": (
            f"I noticed that {worker_name} does not have both a current tax "
            "declaration profile and an approved TFN declaration document. The "
            "timesheet was saved, but the declaration needs attention before "
            "payroll is processed."
        ),
        "source": {
            "type": "worker",
            "id": engagement.worker_id,
            "label": worker_name,
            "url": f"/ui/workers/{engagement.worker_id}",
        },
    }
