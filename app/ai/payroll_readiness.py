"""Deterministic, read-only checks used by the payroll operations assistant."""

from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.assignment_component import AssignmentComponent
from app.models.employee_payment_detail import EmployeePaymentDetail
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.engagement import Engagement
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.worker import Worker
from app.models.worker_document import WorkerDocument
from app.models.work_pattern import WorkPattern


def _name(worker: Worker) -> str:
    return f"{worker.first_name} {worker.last_name}"


def _effective(model, on_date: date):
    return and_(
        model.effective_from <= on_date,
        or_(model.effective_to.is_(None), model.effective_to >= on_date),
    )


def _issue(
    code: str,
    category: str,
    message: str,
    *,
    severity: str = "critical",
    **records: Any,
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "severity": severity,
        "message": message,
        **records,
    }


def find_timesheet_issues(
    db: Session, *, start: date, end: date, as_of: date
) -> list[dict[str, Any]]:
    """Return missing, incomplete, duplicate, and unapproved timesheet issues."""
    if start > end:
        raise ValueError("date_from cannot be after date_to")

    issues: list[dict[str, Any]] = []
    reported_unapproved_headers: set[int] = set()
    scheduled = db.execute(
        select(Assignment, PBTSchedulePeriod, Worker, TimesheetHeader)
        .join(PBTSchedule, PBTSchedule.id == Assignment.pbt_schedule_id)
        .join(PBTSchedulePeriod, PBTSchedulePeriod.pbt_schedule_id == PBTSchedule.id)
        .join(Engagement, Engagement.id == Assignment.engagement_id)
        .join(Worker, Worker.id == Engagement.worker_id)
        .outerjoin(
            TimesheetHeader,
            and_(
                TimesheetHeader.assignment_id == Assignment.id,
                TimesheetHeader.pbt_schedule_period_id == PBTSchedulePeriod.id,
            ),
        )
        .where(
            PBTSchedule.status == "active",
            PBTSchedulePeriod.schedule_type == "timesheet",
            PBTSchedulePeriod.period_end >= start,
            PBTSchedulePeriod.period_start <= end,
            PBTSchedulePeriod.event_date <= as_of,
        )
    ).all()
    for assignment, period, worker, header in scheduled:
        common = {
            "worker_id": worker.id,
            "worker": _name(worker),
            "assignment_id": assignment.id,
            "period_start": period.period_start.isoformat(),
            "period_end": period.period_end.isoformat(),
        }
        if header is None:
            issues.append(_issue(
                "timesheet_missing", "timesheet", "Scheduled timesheet is missing.",
                **common,
            ))
        elif header.status != "approved":
            reported_unapproved_headers.add(header.id)
            issues.append(_issue(
                "timesheet_unapproved", "timesheet",
                f"Timesheet is {header.status} and has not been approved.",
                timesheet_header_id=header.id, status=header.status, **common,
            ))

    headers = db.execute(
        select(TimesheetHeader, Assignment, Engagement, Worker)
        .join(Assignment, Assignment.id == TimesheetHeader.assignment_id)
        .join(Engagement, Engagement.id == Assignment.engagement_id)
        .join(Worker, Worker.id == Engagement.worker_id)
        .where(TimesheetHeader.period_end >= start, TimesheetHeader.period_start <= end)
    ).all()
    header_ids = [row[0].id for row in headers]
    line_counts = dict(db.execute(
        select(Timesheet.timesheet_header_id, func.count(Timesheet.id))
        .where(Timesheet.timesheet_header_id.in_(header_ids))
        .group_by(Timesheet.timesheet_header_id)
    ).all()) if header_ids else {}

    period_keys = Counter(
        (header.assignment_id, header.period_start, header.period_end)
        for header, *_ in headers
    )
    for header, assignment, _engagement, worker in headers:
        common = {
            "worker_id": worker.id,
            "worker": _name(worker),
            "assignment_id": assignment.id,
            "timesheet_header_id": header.id,
            "period_start": header.period_start.isoformat(),
            "period_end": header.period_end.isoformat(),
        }
        if line_counts.get(header.id, 0) == 0:
            issues.append(_issue(
                "timesheet_incomplete", "timesheet", "Timesheet has no daily entries.",
                **common,
            ))
        if header.status != "approved" and header.id not in reported_unapproved_headers:
            issues.append(_issue(
                "timesheet_unapproved", "timesheet",
                f"Timesheet is {header.status} and has not been approved.",
                status=header.status, **common,
            ))
        if period_keys[(header.assignment_id, header.period_start, header.period_end)] > 1:
            issues.append(_issue(
                "timesheet_duplicate_period", "timesheet",
                "More than one timesheet exists for this assignment and period.",
                **common,
            ))

    duplicate_lines = db.execute(
        select(
            Timesheet.assignment_id,
            Timesheet.work_date,
            Timesheet.component_definition_id,
            func.count(Timesheet.id),
            func.min(Timesheet.id),
        )
        .where(
            Timesheet.work_date.between(start, end),
            Timesheet.assignment_id.is_not(None),
        )
        .group_by(
            Timesheet.assignment_id,
            Timesheet.work_date,
            Timesheet.component_definition_id,
        )
        .having(func.count(Timesheet.id) > 1)
    ).all()
    for assignment_id, work_date, component_id, count, first_id in duplicate_lines:
        issues.append(_issue(
            "timesheet_duplicate_entry", "timesheet",
            f"{count} daily entries share the same assignment, date, and component.",
            assignment_id=assignment_id,
            timesheet_id=first_id,
            work_date=work_date.isoformat(),
            component_definition_id=component_id,
        ))

    orphan_unapproved = db.execute(
        select(Timesheet, Engagement, Worker)
        .join(Engagement, Engagement.id == Timesheet.engagement_id)
        .join(Worker, Worker.id == Engagement.worker_id)
        .where(
            Timesheet.timesheet_header_id.is_(None),
            Timesheet.work_date.between(start, end),
            Timesheet.status != "approved",
        )
    ).all()
    for row, _engagement, worker in orphan_unapproved:
        issues.append(_issue(
            "timesheet_unapproved_entry", "timesheet",
            f"Daily timesheet entry is {row.status} and has not been approved.",
            worker_id=worker.id, worker=_name(worker), assignment_id=row.assignment_id,
            timesheet_id=row.id, work_date=row.work_date.isoformat(), status=row.status,
        ))
    return issues


def find_worker_data_issues(db: Session, *, as_of: date) -> list[dict[str, Any]]:
    """Return missing payroll setup data for active workers."""
    issues: list[dict[str, Any]] = []
    workers = db.scalars(
        select(Worker).where(Worker.active.is_(True)).order_by(Worker.id)
    ).all()
    for worker in workers:
        engagements = db.scalars(
            select(Engagement).where(
                Engagement.worker_id == worker.id,
                Engagement.status == "active",
                or_(Engagement.start_date.is_(None), Engagement.start_date <= as_of),
                or_(Engagement.end_date.is_(None), Engagement.end_date >= as_of),
            )
        ).all()
        common = {"worker_id": worker.id, "worker": _name(worker)}
        if not engagements:
            issues.append(_issue(
                "worker_missing_engagement", "engagement",
                "Active worker has no effective active engagement.", **common,
            ))
            continue

        employee_engagements = [
            e for e in engagements
            if e.engagement_type in {"employee", "payg_employee"}
        ]
        if employee_engagements:
            tax = db.scalars(select(EmployeeTaxProfile).where(
                EmployeeTaxProfile.worker_id == worker.id,
                _effective(EmployeeTaxProfile, as_of),
            )).all()
            if len(tax) != 1 or not tax[0].tfn_declaration_received:
                detail = "No complete effective tax profile." if len(tax) <= 1 else (
                    f"Found {len(tax)} overlapping effective tax profiles."
                )
                issues.append(_issue("worker_missing_tax", "tax", detail, **common))

            super_profiles = db.scalars(select(EmployeeSuperProfile).where(
                EmployeeSuperProfile.worker_id == worker.id,
                _effective(EmployeeSuperProfile, as_of),
            )).all()
            super_complete = len(super_profiles) == 1 and all((
                super_profiles[0].fund_name,
                super_profiles[0].fund_usi,
                super_profiles[0].member_number,
            ))
            if not super_complete:
                detail = "No complete effective super profile." if len(super_profiles) <= 1 else (
                    f"Found {len(super_profiles)} overlapping effective super profiles."
                )
                issues.append(_issue("worker_missing_super", "super", detail, **common))

            payments = db.scalars(select(EmployeePaymentDetail).where(
                EmployeePaymentDetail.worker_id == worker.id,
                _effective(EmployeePaymentDetail, as_of),
            )).all()
            payment_complete = len(payments) == 1 and (
                payments[0].payment_method != "bank_transfer" or all((
                    payments[0].account_name, payments[0].bsb,
                    payments[0].account_number,
                ))
            )
            if not payment_complete:
                detail = "No complete effective payment details." if len(payments) <= 1 else (
                    f"Found {len(payments)} overlapping effective payment records."
                )
                issues.append(_issue("worker_missing_bank", "bank", detail, **common))

        assignments = db.scalars(
            select(Assignment).where(
                Assignment.engagement_id.in_([e.id for e in engagements]),
                or_(Assignment.start_date.is_(None), Assignment.start_date <= as_of),
                or_(Assignment.end_date.is_(None), Assignment.end_date >= as_of),
            )
        ).all()
        if not assignments:
            issues.append(_issue(
                "worker_missing_assignment", "engagement",
                "Active engagement has no effective assignment.", **common,
            ))
        for assignment in assignments:
            component_rate = db.scalar(select(func.count(AssignmentComponent.id)).where(
                AssignmentComponent.assignment_id == assignment.id,
                AssignmentComponent.applies_to.in_(("payroll", "both")),
                AssignmentComponent.pay_rate > 0,
                _effective(AssignmentComponent, as_of),
            )) or 0
            pattern_rate = db.scalar(select(func.count(WorkPattern.id)).where(
                WorkPattern.engagement_id == assignment.engagement_id,
                WorkPattern.hourly_rate > 0,
                WorkPattern.start_date <= as_of,
                or_(WorkPattern.end_date.is_(None), WorkPattern.end_date >= as_of),
            )) or 0
            if component_rate == 0 and pattern_rate == 0:
                issues.append(_issue(
                    "worker_missing_rate", "rate", "Assignment has no effective positive pay rate.",
                    assignment_id=assignment.id, **common,
                ))

        required_documents = {"tfn_declaration", "super_choice"} if employee_engagements else {"contractor_insurance"}
        approved_documents = set(db.scalars(select(WorkerDocument.document_type).where(
            WorkerDocument.worker_id == worker.id,
            WorkerDocument.document_type.in_(required_documents),
            WorkerDocument.status == "approved",
            or_(WorkerDocument.expires_on.is_(None), WorkerDocument.expires_on >= as_of),
        )).all())
        for document_type in sorted(required_documents - approved_documents):
            issues.append(_issue(
                "worker_missing_document", "document",
                f"No current approved {document_type.replace('_', ' ')} document.",
                document_type=document_type, severity="warning", **common,
            ))
    return issues


def readiness_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "blocked" if any(i["severity"] == "critical" for i in issues) else (
            "warning" if issues else "ready"
        ),
        "issue_count": len(issues),
        "critical_count": sum(i["severity"] == "critical" for i in issues),
        "warning_count": sum(i["severity"] == "warning" for i in issues),
        "category_counts": dict(sorted(Counter(i["category"] for i in issues).items())),
        "issues": issues,
    }
