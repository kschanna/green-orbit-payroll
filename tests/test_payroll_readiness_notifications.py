from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401  # Register all model metadata.
import app.payroll_readiness_service as service
from app.models.notification import Notification
from app.models.organisation import Base
from app.models.payroll_readiness_run import PayrollReadinessRun
from app.models.user import User


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _issue(code: str) -> dict:
    return {
        "code": code,
        "category": "timesheet",
        "severity": "critical",
        "message": "A safe summary without sensitive data.",
        "worker_id": 42,
        "worker": "Test Worker",
    }


def test_readiness_notifications_are_grouped_deduplicated_and_resolved(monkeypatch):
    current_issues = [_issue("timesheet_missing")]
    monkeypatch.setattr(
        service, "find_timesheet_issues",
        lambda db, start, end, as_of: list(current_issues),
    )
    monkeypatch.setattr(
        service, "find_worker_data_issues", lambda db, as_of: [],
    )

    with _session() as db:
        admin = User(
            email="admin@example.com", password_hash="test", is_active=True,
            role="admin",
        )
        worker_user = User(
            email="worker@example.com", password_hash="test", is_active=True,
            role="worker",
        )
        db.add_all([admin, worker_user])
        db.commit()

        first = service.run_payroll_readiness(db, as_of=date(2026, 10, 28))
        assert first.status == "blocked"
        notifications = db.scalars(select(Notification)).all()
        assert len(notifications) == 1
        assert notifications[0].recipient_user_id == admin.id
        assert notifications[0].action_url == f"/ui/payroll-readiness/{first.id}"
        assert "Test Worker" not in notifications[0].message

        service.run_payroll_readiness(db, as_of=date(2026, 10, 28))
        assert len(db.scalars(select(Notification)).all()) == 1

        current_issues.append(_issue("timesheet_unapproved"))
        service.run_payroll_readiness(db, as_of=date(2026, 10, 28))
        assert len(db.scalars(select(Notification)).all()) == 2

        current_issues.clear()
        resolved = service.run_payroll_readiness(db, as_of=date(2026, 10, 28))
        notifications = db.scalars(
            select(Notification).order_by(Notification.id)
        ).all()
        assert resolved.status == "ready"
        assert len(notifications) == 3
        assert notifications[-1].notification_type == "payroll_readiness_resolved"
        assert len(db.scalars(select(PayrollReadinessRun)).all()) == 4
