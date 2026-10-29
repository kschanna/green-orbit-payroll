from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.main  # noqa: F401 - register all models
import app.worker_documents_router as document_routes
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.notification import Notification
from app.models.organisation import Base
from app.models.user import User
from app.models.worker import Worker
from app.worker_portal_router import mark_tfn_declaration_received


def _engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine


def test_tfn_upload_marks_current_profile_as_received():
    engine = _engine()
    with Session(engine) as db:
        worker = Worker(first_name="Zoe", last_name="Worker", email="zoe@example.com")
        db.add(worker)
        db.flush()
        profile = EmployeeTaxProfile(
            worker_id=worker.id, residency_status="resident",
            claims_tax_free_threshold=True, has_study_loan=False,
            tfn_declaration_received=False, effective_from=date(2026, 1, 1),
        )
        db.add(profile)
        db.flush()

        assert mark_tfn_declaration_received(db, worker.id, as_of=date(2026, 10, 29))
        assert profile.tfn_declaration_received is True


def test_document_alert_is_delivered_once_and_contains_review_action(monkeypatch):
    engine = _engine()
    factory = sessionmaker(bind=engine)
    with factory() as db:
        admin = User(email="admin@example.com", password_hash="test", role="admin", is_active=True)
        db.add(admin)
        db.flush()
        db.add(Notification(
            recipient_user_id=admin.id,
            notification_type="document_ready_for_review",
            title="Zoe uploaded a document",
            message="Zoe's TFN declaration is ready for review and validation.",
            action_url="/ui/workers/1/documents/2/review",
        ))
        db.commit()
        admin_id = admin.id

    monkeypatch.setattr(document_routes, "SessionLocal", factory)
    request = Request({
        "type": "http", "method": "GET",
        "path": "/api/agent-alerts/document-review", "query_string": b"",
        "headers": [], "session": {"user_id": admin_id},
    })
    first = document_routes.next_document_review_alert(request).body.decode()
    second = document_routes.next_document_review_alert(request).body.decode()

    assert '"code":"document_ready_for_review"' in first
    assert '"label":"Review document"' in first
    assert '"alert":null' in second
    with factory() as db:
        assert db.scalar(select(Notification)).read_at is not None
