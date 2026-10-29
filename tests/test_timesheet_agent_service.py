from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401
from app.models.agent_action import AgentAction
from app.models.agent_run import AgentRun
from app.models.agent_task import AgentTask
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.engagement import Engagement
from app.models.organisation import Base, Organisation
from app.models.notification import Notification
from app.models.user import User
from app.models.worker import Worker
from app.models.worker_document import WorkerDocument
from app.timesheet_agent_service import process_timesheet_created


def test_timesheet_agent_persists_deduplicates_and_resolves_task():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        organisation = Organisation(name="Employer", abn="12345678901", country="AU")
        worker = Worker(first_name="Agent", last_name="Worker", email="agent-worker@example.com")
        uploader = User(email="agent-admin@example.com", password_hash="test", role="admin", is_active=True)
        db.add_all([organisation, worker, uploader])
        db.flush()
        portal_user = User(
            email="agent-worker-portal@example.com", password_hash="test",
            role="worker", is_active=True, worker_id=worker.id,
        )
        db.add(portal_user)
        engagement = Engagement(
            worker_id=worker.id, organisation_id=organisation.id,
            engagement_type="employee", status="active",
        )
        db.add(engagement)
        db.flush()

        first = process_timesheet_created(
            db, engagement_id=engagement.id, as_of=date(2026, 10, 28)
        )
        second = process_timesheet_created(
            db, engagement_id=engagement.id, as_of=date(2026, 10, 29)
        )
        db.commit()
        assert first["code"] == second["code"] == "missing_tfn_declaration"
        tasks = db.scalars(select(AgentTask)).all()
        assert len(tasks) == 1
        assert tasks[0].status == "waiting_for_human"
        assert len(db.scalars(select(AgentRun)).all()) == 2
        assert [a.action_type for a in db.scalars(
            select(AgentAction).order_by(AgentAction.id)
        )] == ["task_created", "worker_notified", "task_reconfirmed"]
        messages = db.scalars(select(Notification).where(
            Notification.notification_type == "agent_payroll_setup_required"
        )).all()
        assert len(messages) == 1
        assert messages[0].recipient_user_id == portal_user.id
        assert "TFN declaration" in messages[0].message
        assert "Super choice form" in messages[0].message
        assert messages[0].action_url == "/portal#payroll-setup"

        db.add_all([
            EmployeeTaxProfile(
                worker_id=worker.id, engagement_id=engagement.id,
                residency_status="resident", claims_tax_free_threshold=True,
                has_study_loan=False, tfn_declaration_received=True,
                effective_from=date(2026, 1, 1),
            ),
            WorkerDocument(
                worker_id=worker.id, uploaded_by_user_id=uploader.id,
                document_type="tfn_declaration", original_filename="tfn.pdf",
                content_type="application/pdf", size_bytes=100,
                storage_key="agent/tfn.pdf", status="approved",
            ),
        ])
        db.flush()
        assert process_timesheet_created(
            db, engagement_id=engagement.id, as_of=date(2026, 10, 30)
        ) is None
        db.commit()
        db.refresh(tasks[0])
        assert tasks[0].status == "resolved"
        assert tasks[0].resolved_at is not None
        assert db.scalars(
            select(AgentAction).order_by(AgentAction.id.desc())
        ).first().action_type == "task_resolved"
