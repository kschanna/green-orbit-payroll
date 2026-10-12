import pytest

from app.models.pay_run import PayRun
from app.payroll.pay_run_lifecycle import PayRunLifecycle


def test_draft_to_approved():
    pay_run = PayRun(status="draft")

    PayRunLifecycle().transition(pay_run, "approved")

    assert pay_run.status == "approved"


def test_approved_to_completed():
    pay_run = PayRun(status="approved")

    PayRunLifecycle().transition(pay_run, "completed")

    assert pay_run.status == "completed"


def test_draft_cannot_skip_to_completed():
    pay_run = PayRun(status="draft")

    with pytest.raises(ValueError):
        PayRunLifecycle().transition(pay_run, "completed")


def test_completed_cannot_return_to_draft():
    pay_run = PayRun(status="completed")

    with pytest.raises(ValueError):
        PayRunLifecycle().transition(pay_run, "draft")


def test_invalid_status():
    pay_run = PayRun(status="draft")

    with pytest.raises(ValueError):
        PayRunLifecycle().transition(pay_run, "cancelled")