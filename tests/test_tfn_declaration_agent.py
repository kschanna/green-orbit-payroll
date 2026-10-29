from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401  # Register complete model metadata.
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.engagement import Engagement
from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.worker_document import WorkerDocument
from app.models.user import User
from app.tfn_declaration_agent import missing_tfn_declaration_alert


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _engagement(db: Session, engagement_type: str = "employee"):
    organisation = Organisation(name="Employer", abn="12345678901", country="AU")
    worker = Worker(first_name="Taylor", last_name="Example", email="taylor@example.com")
    db.add_all([organisation, worker])
    db.flush()
    engagement = Engagement(
        worker_id=worker.id, organisation_id=organisation.id,
        engagement_type=engagement_type, status="active",
    )
    db.add(engagement)
    db.flush()
    return worker, engagement


def test_missing_tfn_declaration_returns_safe_agent_alert():
    with _session() as db:
        worker, engagement = _engagement(db)
        alert = missing_tfn_declaration_alert(
            db, engagement.id, as_of=date(2026, 10, 28)
        )
        assert alert["code"] == "missing_tfn_declaration"
        assert alert["source"]["url"] == f"/ui/workers/{worker.id}"
        assert "TFN declaration" in alert["content"]
        assert "tax file number" not in alert["content"].lower()


def test_profile_without_approved_document_still_alerts():
    with _session() as db:
        worker, engagement = _engagement(db)
        db.add(EmployeeTaxProfile(
            worker_id=worker.id, engagement_id=engagement.id,
            residency_status="resident", claims_tax_free_threshold=True,
            has_study_loan=False, tfn_declaration_received=True,
            effective_from=date(2026, 1, 1),
        ))
        db.flush()
        assert missing_tfn_declaration_alert(
            db, engagement.id, as_of=date(2026, 10, 28)
        )["code"] == "missing_tfn_declaration"


def test_current_profile_and_approved_document_suppress_alert():
    with _session() as db:
        worker, engagement = _engagement(db)
        user = User(
            email="uploader@example.com", password_hash="test", role="admin",
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add_all([
            EmployeeTaxProfile(
                worker_id=worker.id, engagement_id=engagement.id,
                residency_status="resident", claims_tax_free_threshold=True,
                has_study_loan=False, tfn_declaration_received=True,
                effective_from=date(2026, 1, 1),
            ),
            WorkerDocument(
                worker_id=worker.id, uploaded_by_user_id=user.id,
                document_type="tfn_declaration", original_filename="tfn.pdf",
                content_type="application/pdf", size_bytes=100,
                storage_key="test/tfn.pdf", status="approved",
            ),
        ])
        db.flush()
        assert missing_tfn_declaration_alert(
            db, engagement.id, as_of=date(2026, 10, 28)
        ) is None


def test_contractor_timesheet_does_not_require_tfn_declaration():
    with _session() as db:
        _worker, engagement = _engagement(db, "contractor")
        assert missing_tfn_declaration_alert(
            db, engagement.id, as_of=date(2026, 10, 28)
        ) is None
