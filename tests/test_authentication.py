import os

# Configure the test database before importing the application.
os.environ["DATABASE_URL"] = "postgresql+psycopg:///green_orbit_payroll_test"
os.environ.setdefault("SESSION_SECRET", "test-secret-not-for-production")
os.environ["SESSION_COOKIE_SECURE"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.security import hash_password


TEST_EMAIL = "auth-test@example.com"
TEST_PASSWORD = "TestPassword123!"


@pytest.fixture
def client():
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == TEST_EMAIL))
        if existing:
            db.delete(existing)
            db.commit()

        user = User(
            email=TEST_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            is_active=True,
        )
        db.add(user)
        db.commit()
        user_id = user.id

    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user:
            db.delete(user)
            db.commit()


def login(client):
    response = client.get("/login")
    assert response.status_code == 200

    # Extract the CSRF token from the login page.
    from html.parser import HTMLParser

    class TokenParser(HTMLParser):
        token = None

        def handle_starttag(self, tag, attrs):
            if tag == "input":
                attributes = dict(attrs)
                if attributes.get("name") == "csrf_token":
                    self.token = attributes.get("value")

    parser = TokenParser()
    parser.feed(response.text)

    assert parser.token

    return client.post(
        "/login",
        data={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "csrf_token": parser.token,
        },
    )


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_succeeds(client):
    response = login(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200


def test_invalid_password_rejected(client):
    response = client.get("/login")
    assert response.status_code == 200

    from html.parser import HTMLParser

    class TokenParser(HTMLParser):
        token = None

        def handle_starttag(self, tag, attrs):
            if tag == "input":
                attributes = dict(attrs)
                if attributes.get("name") == "csrf_token":
                    self.token = attributes.get("value")

    parser = TokenParser()
    parser.feed(response.text)

    assert parser.token

    response = client.post(
        "/login",
        data={
            "email": TEST_EMAIL,
            "password": "WrongPassword123!",
            "csrf_token": parser.token,
        },
    )

    assert response.status_code == 401
    assert "Invalid email or password" in response.text


def test_inactive_user_blocked(client):
    login(client)

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == TEST_EMAIL))
        user.is_active = False
        db.commit()

    response = client.get("/dashboard")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_csrf_blocks_unauthorised_post(client):
    login(client)

    response = client.post(
        "/pay-runs",
        json={},
    )

    assert response.status_code == 403