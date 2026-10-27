import os
from datetime import date

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg:///green_orbit_payroll_test"
)
os.environ.setdefault("SESSION_SECRET", "test-secret-not-for-production")

from app.demo_seed import DemoSeedConfig, preview


def test_demo_seed_preview_caps_workers_and_distributes_engagements():
    result = preview(DemoSeedConfig(
        workers=200, customers=8, seed=42, as_of=date(2026, 10, 26)
    ))

    assert result["batch"] == "ai-demo-42"
    assert result["workers"] == 200
    assert result["engagement_types"] == {
        "company_contractor": 40,
        "payg_contractor": 60,
        "payg_employee": 100,
    }
    assert result["synthetic_email_domain"] == "example.invalid"


@pytest.mark.parametrize("workers", [0, 201])
def test_demo_seed_rejects_worker_counts_outside_safe_limit(workers):
    with pytest.raises(ValueError, match="between 1 and 200"):
        preview(DemoSeedConfig(workers=workers))
