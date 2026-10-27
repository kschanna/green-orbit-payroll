
import pytest
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.worker import Worker
from app.worker_service import WorkerError, WorkerService
from app.workers_router import engagement_type_data


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    Worker.__table__.create(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_create_worker(db):
    worker = WorkerService.create(
        db, "Ahmed", "Khan", "AHMED@example.com"
    )

    assert worker.id is not None
    assert worker.email == "ahmed@example.com"
    assert worker.active is True


def test_duplicate_email(db):
    WorkerService.create(
        db, "Ahmed", "Khan", "ahmed@example.com"
    )

    with pytest.raises(WorkerError):
        WorkerService.create(
            db, "Ahmed", "Khan", "AHMED@example.com"
        )


def test_update_worker(db):
    worker = WorkerService.create(
        db, "Ahmed", "Khan", "ahmed@example.com"
    )

    WorkerService.update(
        db, worker, "Ahmed", "Khan",
        "new@example.com", "0412345678"
    )

    assert worker.email == "new@example.com"
    assert worker.phone == "0412345678"


def test_search_workers(db):
    WorkerService.create(
        db, "Ahmed", "Khan", "ahmed@example.com"
    )

    WorkerService.create(
        db, "Sarah", "Jones", "sarah@example.com"
    )

    assert len(WorkerService.list(db)) == 2
    assert len(WorkerService.list(db, "Ahmed")) == 1
    assert len(WorkerService.list(db, "missing")) == 0


def test_deactivate_reactivate(db):
    worker = WorkerService.create(
        db, "Ahmed", "Khan", "ahmed@example.com"
    )

    WorkerService.set_active(db, worker, False)
    assert worker.active is False

    WorkerService.set_active(db, worker, True)
    assert worker.active is True


def test_delete_worker_without_dependent_records(db):
    worker = WorkerService.create(
        db, "Ahmed", "Khan", "ahmed@example.com"
    )
    worker_id = worker.id

    assert WorkerService.delete(db, worker) == worker_id
    assert WorkerService.get(db, worker_id) is None


def test_delete_worker_with_dependent_records_is_rejected():
    db = Mock()
    db.commit.side_effect = IntegrityError(
        "DELETE FROM workers", {}, Exception("foreign key violation")
    )
    worker = Worker(id=42, first_name="Ahmed", last_name="Khan",
                    email="ahmed@example.com", active=True)

    with pytest.raises(WorkerError, match="Deactivate the worker instead"):
        WorkerService.delete(db, worker)

    db.delete.assert_called_once_with(worker)
    db.rollback.assert_called_once_with()


def test_engagement_types_are_deduplicated_and_active_takes_precedence():
    engagements = [
        Mock(engagement_type="payg_contractor", status="ended"),
        Mock(engagement_type="payg_employee", status="ended"),
        Mock(engagement_type="payg_employee", status="active"),
        Mock(engagement_type="payg_employee", status="active"),
    ]

    assert engagement_type_data(engagements) == [
        {
            "type": "payg_employee",
            "label": "PAYG Employee",
            "badge_class": "badge-engagement-employee",
            "status": "active",
        },
        {
            "type": "payg_contractor",
            "label": "PAYG Contractor",
            "badge_class": "badge-engagement-payg-contractor",
            "status": "ended",
        },
    ]
