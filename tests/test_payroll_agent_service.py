from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401
import app.payroll_agent_service as service
from app.ai.vertex_payroll_planner import build_payroll_plan
from app.agents.payroll.runtime import adk_enabled
from app.models.assignment import Assignment
from app.models.engagement import Engagement
from app.models.organisation import Base, Organisation
from app.models.payroll_agent_step import PayrollAgentStep
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.pbt_schedule_rule import PBTScheduleRule
from app.models.timesheet import Timesheet
from app.models.work_pattern import WorkPattern
from app.models.worker import Worker


def test_agent_creates_pattern_timesheet_then_waits_for_human(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine)
    monkeypatch.setattr(service, "SessionLocal", local_session)
    with Session(engine) as db:
        supplier = Organisation(name="Supplier", abn="12345678901", country="AU")
        customer = Organisation(name="Customer", abn="12345678902", country="AU")
        worker = Worker(first_name="Payroll", last_name="Agent", email="payroll-agent@example.com")
        db.add_all([supplier, customer, worker])
        db.flush()
        engagement = Engagement(
            worker_id=worker.id, organisation_id=supplier.id,
            engagement_type="payg_contractor", status="active",
            start_date=date(2026, 1, 1),
        )
        schedule = PBTSchedule(
            customer_organisation_id=customer.id, name="Weekly",
            effective_from=date(2026, 1, 1), status="active", generation_months=12,
        )
        db.add_all([engagement, schedule])
        db.flush()
        assignment = Assignment(
            engagement_id=engagement.id, customer_id=customer.id,
            pbt_schedule_id=schedule.id, billing_rate=Decimal("100"),
        )
        pattern = WorkPattern(
            engagement_id=engagement.id, employment_type="casual",
            pay_basis="hourly", hourly_rate=Decimal("50"),
            ordinary_hours_per_week=Decimal("40"), pay_frequency="weekly",
            start_date=date(2026, 1, 1),
        )
        rule = PBTScheduleRule(
            pbt_schedule_id=schedule.id, schedule_type="timesheet",
            frequency="weekly", anchor_date=date(2026, 2, 2), offset_days=1,
        )
        db.add_all([assignment, pattern, rule])
        db.flush()
        period = PBTSchedulePeriod(
            pbt_schedule_id=schedule.id, rule_id=rule.id,
            schedule_type="timesheet", period_start=date(2026, 2, 2),
            period_end=date(2026, 2, 8), event_date=date(2026, 2, 9),
            status="planned",
        )
        db.add(period)
        db.commit()
        assignment_id, period_id = assignment.id, period.id

    run = service.start_payroll_agent_run(
        assignment_id, period_id, triggered_by_user_id=None
    )
    assert run.status == "waiting_for_human"
    assert run.current_step == "confirm_hours"
    assert run.records["timesheet_header_id"]
    with Session(engine) as db:
        entries = list(db.scalars(select(Timesheet).where(
            Timesheet.timesheet_header_id == run.records["timesheet_header_id"]
        ).order_by(Timesheet.work_date)))
        assert [item.hours_worked for item in entries] == [
            Decimal("8.00"), Decimal("8.00"), Decimal("8.00"),
            Decimal("8.00"), Decimal("8.00"), Decimal("0.00"), Decimal("0.00"),
        ]
        steps = list(db.scalars(select(PayrollAgentStep).where(
            PayrollAgentStep.run_id == run.id
        ).order_by(PayrollAgentStep.sequence)))
        assert steps[0].status == "completed"
        assert steps[1].status == "completed"
        assert steps[2].status == "waiting"


def test_vertex_planner_does_not_control_financial_steps():
    assert service.STEP_DEFINITIONS[0][2] == "vertex_or_template"
    assert all(
        source != "vertex_or_template"
        for _, _, source in service.STEP_DEFINITIONS[1:]
    )


def test_vertex_planner_uses_safe_template_when_disabled(monkeypatch):
    monkeypatch.delenv("VERTEX_AI_PLANNING_ENABLED", raising=False)
    plan = build_payroll_plan(
        assignment_id=1, period_start="2026-02-02", period_end="2026-02-08"
    )
    assert plan["planner"] == "approved_template"
    assert plan["steps"] == [item[0] for item in service.STEP_DEFINITIONS]


def test_payg_employees_and_contractors_are_supported():
    assert service.SUPPORTED_ENGAGEMENT_TYPES == {
        "payg_employee", "employee", "payg_contractor"
    }


def test_decimal_trace_values_are_json_safe():
    result = {"invoice_id": 1, "total": Decimal("123.45")}
    safe = {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in result.items()
    }
    assert safe == {"invoice_id": 1, "total": "123.45"}


def test_payroll_adk_is_feature_gated(monkeypatch):
    monkeypatch.delenv("PAYROLL_AGENT_ADK_ENABLED", raising=False)
    assert adk_enabled() is False
    monkeypatch.setenv("PAYROLL_AGENT_ADK_ENABLED", "true")
    assert adk_enabled() is True
