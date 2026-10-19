"""Canonical engagement ownership tests (no legacy Employee fixture)."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def make_entities(session):
    organisation = Organisation(name="Integrity Test", abn="12345678901", country="AU")
    worker = Worker(first_name="Test", last_name="Worker", email="integrity@example.com")
    session.add_all([organisation, worker])
    session.flush()
    return organisation, worker


def test_engagement_links_correct_worker_and_organisation(session):
    organisation, worker = make_entities(session)
    engagement = Engagement(
        worker_id=worker.id, organisation_id=organisation.id,
        engagement_type="employee", status="active",
    )
    session.add(engagement)
    session.flush()
    assert session.get(Engagement, engagement.id).worker.id == worker.id
    assert engagement.organisation.id == organisation.id


def test_missing_engagement_returns_none(session):
    assert session.get(Engagement, 999999) is None


def test_worker_can_have_multiple_distinct_engagements(session):
    organisation, worker = make_entities(session)
    second = Organisation(name="Second Organisation", abn="98765432109", country="AU")
    session.add(second)
    session.flush()
    session.add_all([
        Engagement(worker_id=worker.id, organisation_id=organisation.id,
                   engagement_type="employee", status="active"),
        Engagement(worker_id=worker.id, organisation_id=second.id,
                   engagement_type="employee", status="active"),
    ])
    session.flush()
    records = session.scalars(select(Engagement).where(Engagement.worker_id == worker.id)).all()
    assert len(records) == 2
    assert {e.organisation_id for e in records} == {organisation.id, second.id}
