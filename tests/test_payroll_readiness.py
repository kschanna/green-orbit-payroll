from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai.payroll_readiness import (
    find_timesheet_issues,
    find_worker_data_issues,
    readiness_summary,
)
from app.models.assignment import Assignment
from app.models.component_definition import ComponentDefinition  # noqa: F401
from app.models.employee_payment_detail import EmployeePaymentDetail
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.engagement import Engagement
from app.models.organisation import Base, Organisation
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.user import User  # noqa: F401
from app.models.worker import Worker
from app.models.work_pattern import WorkPattern
from app.models.pbt_schedule_rule import PBTScheduleRule
import app.main  # noqa: F401  # Register the complete application metadata.


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _worker_setup(db: Session):
    employer = Organisation(name="Employer", abn="12345678901", country="AU")
    customer = Organisation(name="Customer", abn="98765432109", country="AU")
    worker = Worker(first_name="Alex", last_name="Readiness", email="alex@example.com")
    db.add_all([employer, customer, worker])
    db.flush()
    engagement = Engagement(
        worker_id=worker.id,
        organisation_id=employer.id,
        engagement_type="employee",
        status="active",
        start_date=date(2026, 1, 1),
    )
    db.add(engagement)
    db.flush()
    assignment = Assignment(
        engagement_id=engagement.id,
        customer_id=customer.id,
        billing_rate=Decimal("100"),
        start_date=date(2026, 1, 1),
    )
    db.add(assignment)
    db.flush()
    return worker, engagement, assignment


def test_worker_readiness_reports_each_missing_setup_category():
    with _session() as db:
        worker, _engagement, assignment = _worker_setup(db)
        issues = find_worker_data_issues(db, as_of=date(2026, 10, 28))

        assert {issue["code"] for issue in issues} == {
            "worker_missing_tax",
            "worker_missing_super",
            "worker_missing_bank",
            "worker_missing_rate",
            "worker_missing_document",
        }
        assert {issue.get("document_type") for issue in issues} >= {
            "tfn_declaration", "super_choice"
        }
        rate_issue = next(i for i in issues if i["code"] == "worker_missing_rate")
        assert rate_issue["worker_id"] == worker.id
        assert rate_issue["assignment_id"] == assignment.id


def test_effective_profiles_and_work_pattern_clear_core_worker_issues():
    with _session() as db:
        worker, engagement, _assignment = _worker_setup(db)
        effective = date(2026, 1, 1)
        db.add_all([
            EmployeeTaxProfile(
                worker_id=worker.id, residency_status="resident",
                claims_tax_free_threshold=True, has_study_loan=False,
                tfn_declaration_received=True, effective_from=effective,
            ),
            EmployeeSuperProfile(
                worker_id=worker.id, fund_name="Fund", fund_usi="USI",
                member_number="MEMBER", effective_from=effective,
            ),
            EmployeePaymentDetail(
                worker_id=worker.id, payment_method="bank_transfer",
                account_name="Alex Readiness", bsb="123456",
                account_number="12345678", effective_from=effective,
            ),
            WorkPattern(
                engagement_id=engagement.id, employment_type="full_time",
                pay_basis="hourly", hourly_rate=Decimal("50"),
                ordinary_hours_per_week=Decimal("38"), pay_frequency="weekly",
                start_date=effective,
            ),
        ])
        db.flush()

        codes = {i["code"] for i in find_worker_data_issues(
            db, as_of=date(2026, 10, 28)
        )}
        assert not codes & {
            "worker_missing_tax", "worker_missing_super",
            "worker_missing_bank", "worker_missing_rate",
        }
        assert codes == {"worker_missing_document"}


def test_timesheet_readiness_finds_missing_incomplete_duplicate_and_unapproved():
    with _session() as db:
        _worker, engagement, assignment = _worker_setup(db)
        schedule = PBTSchedule(
            customer_organisation_id=assignment.customer_id,
            name="Weekly", effective_from=date(2026, 1, 1), status="active",
        )
        db.add(schedule)
        db.flush()
        rule = PBTScheduleRule(
            pbt_schedule_id=schedule.id, schedule_type="timesheet",
            frequency="weekly", anchor_date=date(2026, 10, 19),
            offset_days=1, active=True,
        )
        db.add(rule)
        db.flush()
        assignment.pbt_schedule_id = schedule.id
        period = PBTSchedulePeriod(
            pbt_schedule_id=schedule.id, rule_id=rule.id, schedule_type="timesheet",
            period_start=date(2026, 10, 19), period_end=date(2026, 10, 25),
            event_date=date(2026, 10, 26),
        )
        db.add(period)
        db.flush()
        first = TimesheetHeader(
            engagement_id=engagement.id, assignment_id=assignment.id,
            pbt_schedule_period_id=period.id, period_type="weekly",
            period_start=period.period_start, period_end=period.period_end,
            status="submitted", source="worker",
        )
        duplicate = TimesheetHeader(
            engagement_id=engagement.id, assignment_id=assignment.id,
            period_type="weekly", period_start=period.period_start,
            period_end=period.period_end, status="draft", source="manual",
        )
        db.add_all([first, duplicate])
        db.flush()
        db.add_all([
            Timesheet(
                engagement_id=engagement.id, assignment_id=assignment.id,
                timesheet_header_id=first.id, work_date=date(2026, 10, 20),
                hours_worked=Decimal("8"), status="draft",
            ),
            Timesheet(
                engagement_id=engagement.id, assignment_id=assignment.id,
                timesheet_header_id=first.id, work_date=date(2026, 10, 20),
                hours_worked=Decimal("1"), status="draft",
            ),
        ])
        db.flush()

        issues = find_timesheet_issues(
            db,
            start=date(2026, 10, 19),
            end=date(2026, 10, 25),
            as_of=date(2026, 10, 28),
        )
        codes = {issue["code"] for issue in issues}
        assert "timesheet_unapproved" in codes
        assert "timesheet_incomplete" in codes
        assert "timesheet_duplicate_period" in codes
        assert "timesheet_duplicate_entry" in codes
        assert readiness_summary(issues)["status"] == "blocked"


def test_due_scheduled_period_without_header_is_missing():
    with _session() as db:
        _worker, _engagement, assignment = _worker_setup(db)
        schedule = PBTSchedule(
            customer_organisation_id=assignment.customer_id,
            name="Weekly missing", effective_from=date(2026, 1, 1), status="active",
        )
        db.add(schedule)
        db.flush()
        rule = PBTScheduleRule(
            pbt_schedule_id=schedule.id, schedule_type="timesheet",
            frequency="weekly", anchor_date=date(2026, 10, 19),
            offset_days=1, active=True,
        )
        db.add(rule)
        db.flush()
        assignment.pbt_schedule_id = schedule.id
        db.add(PBTSchedulePeriod(
            pbt_schedule_id=schedule.id, rule_id=rule.id, schedule_type="timesheet",
            period_start=date(2026, 10, 19), period_end=date(2026, 10, 25),
            event_date=date(2026, 10, 26),
        ))
        db.flush()

        codes = {i["code"] for i in find_timesheet_issues(
            db, start=date(2026, 10, 19), end=date(2026, 10, 25),
            as_of=date(2026, 10, 28),
        )}
        assert "timesheet_missing" in codes
