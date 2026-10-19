
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.worker import Worker
from app.worker_service import WorkerError, WorkerService


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
