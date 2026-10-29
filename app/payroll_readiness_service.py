"""Persist payroll-readiness audits and notify administrators about changes."""

import hashlib
import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.payroll_readiness import find_timesheet_issues, find_worker_data_issues, readiness_summary
from app.models.notification import Notification
from app.models.payroll_readiness_run import PayrollReadinessRun
from app.models.user import User


def _fingerprint(issues: list[dict]) -> str:
    stable = [{key: value for key, value in issue.items() if key != "message"} for issue in issues]
    stable.sort(key=lambda item: json.dumps(item, sort_keys=True))
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _notification_copy(summary: dict) -> tuple[str, str, str]:
    if summary["status"] == "ready":
        return "payroll_readiness_resolved", "Payroll readiness checks are clear", "All previously reported payroll readiness issues have been resolved."
    message = (
        f"{summary['critical_count']} critical issue{'s' if summary['critical_count'] != 1 else ''} and "
        f"{summary['warning_count']} warning{'s' if summary['warning_count'] != 1 else ''} were found."
    )
    return "payroll_readiness_changed", "Payroll readiness requires attention", message


def run_payroll_readiness(db: Session, *, as_of: date | None = None, date_from: date | None = None, date_to: date | None = None, triggered_by_user_id: int | None = None) -> PayrollReadinessRun:
    as_of = as_of or date.today()
    date_to = date_to or as_of
    date_from = date_from or (date_to - timedelta(days=14))
    if date_from > date_to:
        raise ValueError("date_from cannot be after date_to")
    if (date_to - date_from).days > 93:
        raise ValueError("Readiness date range cannot exceed 93 days")

    issues = find_timesheet_issues(db, start=date_from, end=date_to, as_of=as_of)
    issues.extend(find_worker_data_issues(db, as_of=as_of))
    summary = readiness_summary(issues)
    fingerprint = _fingerprint(issues)
    previous = db.scalar(select(PayrollReadinessRun).order_by(PayrollReadinessRun.id.desc()).limit(1))
    run = PayrollReadinessRun(
        triggered_by_user_id=triggered_by_user_id, as_of=as_of, date_from=date_from,
        date_to=date_to, status=summary["status"], issue_count=summary["issue_count"],
        critical_count=summary["critical_count"], warning_count=summary["warning_count"],
        fingerprint=fingerprint, issues=issues,
    )
    db.add(run)
    db.flush()

    changed = previous is None or previous.fingerprint != fingerprint
    resolved = previous is not None and previous.issue_count > 0 and not issues
    if changed and (issues or resolved):
        notification_type, title, message = _notification_copy(summary)
        admins = db.scalars(select(User).where(User.is_active.is_(True), User.role == "admin")).all()
        for admin in admins:
            db.add(Notification(
                recipient_user_id=admin.id, notification_type=notification_type,
                title=title, message=message, action_url=f"/ui/payroll-readiness/{run.id}",
            ))
    db.commit()
    db.refresh(run)
    return run
