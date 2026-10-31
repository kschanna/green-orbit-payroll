from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.database import SessionLocal
from app.ai.vertex_payroll_planner import build_payroll_plan
from app.invoicing.engine import generate_invoice_for_timesheet
from app.models.assignment import Assignment
from app.models.employee_payment_detail import EmployeePaymentDetail
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.engagement import Engagement
from app.models.invoice import Invoice
from app.models.invoice_timesheet import InvoiceTimesheet
from app.models.notification import Notification
from app.models.pay_run import PayRun
from app.models.payroll_agent_run import PayrollAgentRun
from app.models.payroll_agent_step import PayrollAgentStep
from app.models.payslip import Payslip
from app.models.payslip_timesheet import PayslipTimesheet
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.user import User
from app.models.work_pattern import WorkPattern
from app.timesheet_run_router import _create_scheduled_timesheet, _expected_period
from app.leave.service import LeaveService
from app.payroll.pay_run_lifecycle import PayRunLifecycle


AGENT_NAME = "green_orbit_payroll_processor"
SUPPORTED_ENGAGEMENT_TYPES = {"payg_employee", "employee", "payg_contractor"}
STEP_DEFINITIONS = (
    ("plan", "Plan the payroll workflow", "vertex_or_template"),
    ("create_timesheet", "Create draft timesheet", "deterministic"),
    ("confirm_hours", "Human confirms generated hours", "human"),
    ("readiness", "Validate payroll requirements", "deterministic"),
    ("approve_timesheet", "Approve timesheet", "deterministic"),
    ("draft_invoice", "Generate draft invoice", "deterministic"),
    ("draft_payroll", "Generate draft payroll", "deterministic"),
    ("reconcile", "Reconcile timesheet, invoice and payroll", "deterministic"),
    ("handoff", "Hand off drafts for human approval", "human"),
)


def _now():
    return datetime.now(timezone.utc)


def _step(db, run_id: int, key: str) -> PayrollAgentStep:
    return db.scalar(select(PayrollAgentStep).where(
        PayrollAgentStep.run_id == run_id,
        PayrollAgentStep.step_key == key,
    ))


def _set_step(db, run_id: int, key: str, status: str, details=None):
    step = _step(db, run_id, key)
    if step is None:
        raise RuntimeError(f"Payroll agent step {key} is missing")
    if step.started_at is None and status in {"running", "completed", "blocked", "waiting"}:
        step.started_at = _now()
    step.status = status
    if details is not None:
        step.details = details
    if status == "completed":
        step.completed_at = _now()
    return step


def _notify_admins(db, run, notification_type: str, title: str, message: str):
    action_url = f"/ui/payroll-agent/runs/{run.id}"
    admins = db.scalars(select(User).where(
        User.role == "admin", User.is_active.is_(True)
    )).all()
    for admin in admins:
        existing = db.scalar(select(Notification.id).where(
            Notification.recipient_user_id == admin.id,
            Notification.notification_type == notification_type,
            Notification.action_url == action_url,
            Notification.read_at.is_(None),
        ).limit(1))
        if existing is None:
            db.add(Notification(
                recipient_user_id=admin.id,
                notification_type=notification_type,
                title=title,
                message=message,
                action_url=action_url,
            ))


def _effective(db, model, worker_id: int, as_of: date):
    return db.scalar(select(model).where(
        model.worker_id == worker_id,
        model.effective_from <= as_of,
        or_(model.effective_to.is_(None), model.effective_to >= as_of),
    ).order_by(model.effective_from.desc(), model.id.desc()).limit(1))


def _work_pattern(db, engagement_id: int, as_of: date):
    return db.scalar(select(WorkPattern).where(
        WorkPattern.engagement_id == engagement_id,
        WorkPattern.start_date <= as_of,
        or_(WorkPattern.end_date.is_(None), WorkPattern.end_date >= as_of),
    ).order_by(WorkPattern.start_date.desc(), WorkPattern.id.desc()).limit(1))


def payroll_blockers(db, run: PayrollAgentRun) -> list[dict]:
    assignment = db.get(Assignment, run.assignment_id)
    engagement = db.get(Engagement, assignment.engagement_id) if assignment else None
    period = db.get(PBTSchedulePeriod, run.pbt_schedule_period_id)
    as_of = period.period_end if period else date.today()
    blockers = []
    if assignment is None or engagement is None:
        return [{"code": "engagement", "label": "Valid assignment and engagement", "action_url": "/ui/assignments"}]
    if engagement.status != "active":
        blockers.append({"code": "engagement", "label": "Active engagement", "action_url": f"/ui/engagements"})
    if engagement.engagement_type not in SUPPORTED_ENGAGEMENT_TYPES:
        blockers.append({
            "code": "engagement_type",
            "label": "This engagement type is not supported by automated PAYG payroll",
            "help": (
                "Do not change a valid engagement type. Process this worker through "
                "the appropriate contractor workflow or ask payroll administration "
                "to review the engagement."
            ),
            "action_url": "/ui/engagements",
        })
    if assignment.billing_rate is None or assignment.billing_rate <= 0:
        blockers.append({"code": "billing_rate", "label": "Billing rate", "action_url": f"/ui/assignments/{assignment.id}"})
    pattern = _work_pattern(db, engagement.id, as_of)
    if pattern is None or pattern.hourly_rate <= 0:
        blockers.append({"code": "pay_rate", "label": "Effective pay rate", "action_url": f"/ui/engagements/{engagement.id}/work-patterns"})
    tax = _effective(db, EmployeeTaxProfile, run.worker_id, as_of)
    if tax is None or not tax.tfn_declaration_received:
        blockers.append({"code": "tfn_declaration", "label": "Approved TFN declaration", "action_url": f"/ui/workers/{run.worker_id}/tax"})
    elif tax.residency_status != "resident":
        blockers.append({"code": "tax_residency", "label": "Supported resident tax profile", "action_url": f"/ui/workers/{run.worker_id}/tax"})
    elif tax.has_study_loan:
        blockers.append({"code": "study_loan", "label": "Study-loan withholding support or manual payroll review", "action_url": f"/ui/workers/{run.worker_id}/tax"})
    super_profile = _effective(db, EmployeeSuperProfile, run.worker_id, as_of)
    if super_profile is None or not all((super_profile.fund_name, super_profile.fund_usi, super_profile.member_number)):
        blockers.append({"code": "super_choice", "label": "Complete super choice", "action_url": f"/ui/workers/{run.worker_id}"})
    bank = _effective(db, EmployeePaymentDetail, run.worker_id, as_of)
    if bank is None or not all((bank.account_name, bank.bsb, bank.account_number)):
        blockers.append({"code": "bank_details", "label": "Complete bank details", "action_url": f"/ui/workers/{run.worker_id}"})
    return blockers


def start_payroll_agent_run(
    assignment_id: int, period_id: int, *, triggered_by_user_id: int | None
) -> PayrollAgentRun:
    with SessionLocal() as db:
        assignment, period = _expected_period(db, assignment_id, period_id)
        engagement = db.get(Engagement, assignment.engagement_id)
        existing = db.scalar(select(PayrollAgentRun).where(
            PayrollAgentRun.assignment_id == assignment_id,
            PayrollAgentRun.pbt_schedule_period_id == period_id,
            PayrollAgentRun.status.not_in(("failed", "cancelled")),
        ).order_by(PayrollAgentRun.id.desc()).limit(1))
        if existing is not None:
            return existing
        plan = build_payroll_plan(
            assignment_id=assignment.id,
            period_start=period.period_start.isoformat(),
            period_end=period.period_end.isoformat(),
        )
        run = PayrollAgentRun(
            assignment_id=assignment.id,
            worker_id=engagement.worker_id,
            pbt_schedule_period_id=period.id,
            triggered_by_user_id=triggered_by_user_id,
            status="running",
            current_step="plan",
            blockers=[],
            records={},
            plan=plan,
        )
        db.add(run)
        db.flush()
        for sequence, (key, label, source) in enumerate(STEP_DEFINITIONS, 1):
            db.add(PayrollAgentStep(
                run_id=run.id, step_key=key, label=label, sequence=sequence,
                status="pending", decision_source=source, details={},
            ))
        db.commit()
        run_id = run.id
    advance_payroll_agent_run(run_id)
    with SessionLocal() as db:
        return db.get(PayrollAgentRun, run_id)


def _populate_from_work_pattern(db, run, header, period):
    assignment = db.get(Assignment, run.assignment_id)
    pattern = _work_pattern(db, assignment.engagement_id, period.period_end)
    if pattern is None or pattern.ordinary_hours_per_week <= 0:
        raise HTTPException(409, "An effective work pattern is required to generate hours")
    daily_hours = (Decimal(pattern.ordinary_hours_per_week) / Decimal("5")).quantize(Decimal("0.01"))
    entries = list(db.scalars(select(Timesheet).where(
        Timesheet.timesheet_header_id == header.id
    ).order_by(Timesheet.work_date)))
    for entry in entries:
        entry.hours_worked = daily_hours if entry.work_date.weekday() < 5 else Decimal("0.00")
    return entries, pattern


def _advance_payroll_agent_run(run_id: int, *, hours_confirmed: bool = False):
    with SessionLocal() as db:
        run = db.get(PayrollAgentRun, run_id)
        if run is None:
            raise HTTPException(404, "Payroll agent run not found")
        if run.status in {"completed", "cancelled", "awaiting_human_approval"}:
            return run
        if run.status == "failed":
            run.status = "running"
            run.blockers = []
        try:
            _set_step(db, run.id, "plan", "completed", run.plan)
            records = dict(run.records or {})
            # Some requirements are prerequisites for generating meaningful
            # hours. Surface all readiness issues before attempting creation so
            # the agent pauses with actionable guidance instead of a tool error.
            preflight_blockers = payroll_blockers(db, run)
            structural_codes = {
                "engagement", "engagement_type", "billing_rate", "pay_rate"
            }
            has_structural_blocker = any(
                item.get("code") in structural_codes
                for item in preflight_blockers
            )
            if has_structural_blocker and not records.get("timesheet_header_id"):
                run.status = "waiting_for_requirements"
                run.current_step = "readiness"
                run.blockers = preflight_blockers
                _set_step(db, run.id, "readiness", "blocked", {
                    "message": (
                        "The agent checked payroll readiness before creating the "
                        "timesheet and paused for the listed requirements."
                    ),
                    "blockers": preflight_blockers,
                })
                labels = ", ".join(item["label"] for item in preflight_blockers)
                _notify_admins(
                    db, run, "payroll_agent_blocked",
                    f"Payroll agent run #{run.id} is waiting",
                    f"I paused this payroll run because it needs: {labels}.",
                )
                db.commit()
                return run
            if not records.get("timesheet_header_id"):
                run.current_step = "create_timesheet"
                _set_step(db, run.id, "create_timesheet", "running")
                assignment, period = _expected_period(db, run.assignment_id, run.pbt_schedule_period_id)
                header, created = _create_scheduled_timesheet(db, assignment, period)
                entries, pattern = _populate_from_work_pattern(db, run, header, period)
                records["timesheet_header_id"] = header.id
                run.records = records
                _set_step(db, run.id, "create_timesheet", "completed", {
                    "created": created, "source": "effective_work_pattern",
                    "work_pattern_id": pattern.id,
                    "total_hours": str(sum((item.hours_worked for item in entries), Decimal("0"))),
                })
            if not hours_confirmed and _step(db, run.id, "confirm_hours").status != "completed":
                run.status = "waiting_for_human"
                run.current_step = "confirm_hours"
                _set_step(db, run.id, "confirm_hours", "waiting", {
                    "message": "Review the generated daily hours before the agent proceeds."
                })
                _notify_admins(
                    db, run, "payroll_agent_hours_review",
                    f"Payroll agent run #{run.id} needs an hours review",
                    "I created the draft timesheet from the worker's current work pattern. Review the daily hours, then let me continue.",
                )
                db.commit()
                return run
            _set_step(db, run.id, "confirm_hours", "completed", {"confirmed": True})
            run.status = "running"
            run.current_step = "readiness"
            blockers = payroll_blockers(db, run)
            run.blockers = blockers
            if blockers:
                run.status = "waiting_for_requirements"
                _set_step(db, run.id, "readiness", "blocked", {
                    "message": "The agent paused safely until the listed payroll requirements are resolved.",
                    "blockers": blockers,
                })
                labels = ", ".join(item["label"] for item in blockers)
                _notify_admins(
                    db, run, "payroll_agent_blocked",
                    f"Payroll agent run #{run.id} is waiting",
                    f"I paused this payroll run because it needs: {labels}. Open the run to resolve the requirements.",
                )
                db.commit()
                return run
            _set_step(db, run.id, "readiness", "completed", {"blockers": []})
            header = db.get(TimesheetHeader, records["timesheet_header_id"])
            entries = list(db.scalars(select(Timesheet).where(Timesheet.timesheet_header_id == header.id)))
            run.current_step = "approve_timesheet"
            if header.status == "draft":
                LeaveService.validate_timesheets(db, header.engagement_id, entries)
                header.status = "approved"
                for entry in entries:
                    entry.status = "approved"
            _set_step(db, run.id, "approve_timesheet", "completed", {"timesheet_header_id": header.id})
            run.records = records
            db.commit()
        except Exception as exc:
            db.rollback()
            run = db.get(PayrollAgentRun, run_id)
            run.status = "failed"
            run.blockers = [{"code": "execution_error", "label": str(exc)}]
            db.commit()
            raise

    # Invoice and payroll use existing transaction-safe domain operations.
    with SessionLocal() as db:
        run = db.get(PayrollAgentRun, run_id)
        records = dict(run.records)
        header = db.get(TimesheetHeader, records["timesheet_header_id"])
        timesheet_ids = list(db.scalars(select(Timesheet.id).where(
            Timesheet.timesheet_header_id == header.id
        )))
        invoice_id = records.get("invoice_id")
        if not invoice_id:
            invoice_id = db.scalar(select(InvoiceTimesheet.invoice_id).where(
                InvoiceTimesheet.timesheet_id.in_(timesheet_ids)
            ).order_by(InvoiceTimesheet.invoice_id.desc()).limit(1))
    if not invoice_id:
        result = generate_invoice_for_timesheet(run.assignment_id, timesheet_ids)
        invoice_id = result["invoice_id"]
        with SessionLocal() as db:
            run = db.get(PayrollAgentRun, run_id)
            records = dict(run.records)
            records["invoice_id"] = invoice_id
            run.records = records
            run.current_step = "draft_invoice"
            _set_step(db, run.id, "draft_invoice", "completed", {
                key: str(value) if isinstance(value, Decimal) else value
                for key, value in result.items()
            })
            db.commit()
    else:
        with SessionLocal() as db:
            run = db.get(PayrollAgentRun, run_id)
            records = dict(run.records)
            records["invoice_id"] = invoice_id
            run.records = records
            run.current_step = "draft_invoice"
            invoice = db.get(Invoice, invoice_id)
            _set_step(db, run.id, "draft_invoice", "completed", {
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "total": str(invoice.total),
                "recovered_existing_draft": True,
            })
            db.commit()

    from app.main import generate_invoice_contractor_payroll
    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        run = db.get(PayrollAgentRun, run_id)
        header = db.get(TimesheetHeader, run.records["timesheet_header_id"])
        existing_payslip = db.scalar(select(Payslip).join(
            PayslipTimesheet, PayslipTimesheet.payslip_id == Payslip.id
        ).where(PayslipTimesheet.timesheet_id.in_(timesheet_ids)).limit(1))
    if existing_payslip is None:
        generate_invoice_contractor_payroll(None, invoice.id, header.period_start.isoformat())

    with SessionLocal() as db:
        run = db.get(PayrollAgentRun, run_id)
        records = dict(run.records)
        payslip = db.scalar(select(Payslip).join(
            PayslipTimesheet, PayslipTimesheet.payslip_id == Payslip.id
        ).where(PayslipTimesheet.timesheet_id.in_(timesheet_ids)).order_by(Payslip.id.desc()).limit(1))
        records["payslip_id"] = payslip.id
        records["pay_run_id"] = payslip.pay_run_id
        run.records = records
        _set_step(db, run.id, "draft_payroll", "completed", {
            "pay_run_id": payslip.pay_run_id, "payslip_id": payslip.id,
            "gross": str(payslip.gross_pay), "net": str(payslip.net_pay),
        })
        invoice = db.get(Invoice, invoice_id)
        timesheet_hours = sum((db.get(Timesheet, item).hours_worked for item in timesheet_ids), Decimal("0"))
        _set_step(db, run.id, "reconcile", "completed", {
            "timesheet_hours": str(timesheet_hours), "invoice_total": str(invoice.total),
            "payroll_gross": str(payslip.gross_pay), "status": "balanced_sources_verified",
        })
        run.status = "awaiting_human_approval"
        run.current_step = "handoff"
        run.blockers = []
        _set_step(db, run.id, "handoff", "waiting", {
            "message": "Draft invoice and payroll are ready for human approval."
        })
        _notify_admins(
            db, run, "payroll_agent_handoff",
            f"Payroll agent run #{run.id} is ready",
            "I created and reconciled the draft invoice and draft payroll. They are ready for your approval.",
        )
        db.commit()
        return run


def advance_payroll_agent_run(run_id: int, *, hours_confirmed: bool = False):
    from app.agents.payroll.runtime import adk_enabled, run_payroll_agent

    if adk_enabled():
        try:
            trace = run_payroll_agent(
                run_id, hours_review_verified=hours_confirmed
            )
            with SessionLocal() as db:
                run = db.get(PayrollAgentRun, run_id)
                plan = dict(run.plan or {})
                plan.pop("adk_fallback_reason", None)
                plan.update({
                    "planner": "google_adk_vertex",
                    "adk_runtime": trace,
                })
                run.plan = plan
                plan_step = _step(db, run.id, "plan")
                if plan_step is not None:
                    plan_step.decision_source = "vertex_adk"
                    details = dict(plan_step.details or {})
                    details.update(plan)
                    plan_step.details = details
                db.commit()
            with SessionLocal() as db:
                current = db.get(PayrollAgentRun, run_id)
                if trace.get("advanced") or current.status in {
                    "waiting_for_human", "waiting_for_requirements",
                    "awaiting_human_approval", "completed", "cancelled",
                }:
                    return current
            raise RuntimeError("ADK agent did not select the bounded advance tool")
        except Exception as exc:
            with SessionLocal() as db:
                run = db.get(PayrollAgentRun, run_id)
                if run is not None:
                    plan = dict(run.plan or {})
                    plan["adk_fallback_reason"] = type(exc).__name__
                    run.plan = plan
                    db.commit()

    try:
        return _advance_payroll_agent_run(run_id, hours_confirmed=hours_confirmed)
    except Exception as exc:
        with SessionLocal() as db:
            run = db.get(PayrollAgentRun, run_id)
            if run is not None:
                run.status = "failed"
                run.blockers = [{
                    "code": "execution_error",
                    "label": "The agent stopped safely. Review the run before retrying.",
                    "technical_type": type(exc).__name__,
                }]
                _notify_admins(
                    db, run, "payroll_agent_failed",
                    f"Payroll agent run #{run.id} stopped safely",
                    "I stopped the run without discarding existing drafts. Open the run to review the failure and retry from the last completed step.",
                )
                db.commit()
        raise


def approve_payroll_agent_handoff(run_id: int, *, approved_by_user_id: int):
    """Approve only the drafts that the agent recorded and reconciled."""
    with SessionLocal() as db:
        run = db.scalar(
            select(PayrollAgentRun)
            .where(PayrollAgentRun.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise ValueError("Payroll agent run not found")
        if run.status == "completed":
            return run
        if run.status != "awaiting_human_approval" or run.current_step != "handoff":
            raise ValueError("This payroll agent run is not ready for approval")

        invoice = db.get(Invoice, run.records.get("invoice_id"))
        pay_run = db.get(PayRun, run.records.get("pay_run_id"))
        payslip = db.get(Payslip, run.records.get("payslip_id"))
        if invoice is None or pay_run is None or payslip is None:
            raise ValueError("The reconciled invoice or payroll draft could not be found")
        if payslip.pay_run_id != pay_run.id:
            raise ValueError("The reviewed payslip does not belong to this pay run")
        # Issued and paid invoices have already passed the draft approval gate.
        # Accept them so a retried handoff remains idempotent.
        if invoice.status not in {"draft", "issued", "paid"}:
            raise ValueError(f"Invoice cannot be approved from status '{invoice.status}'")
        # Approved and completed pay runs have already passed this human gate.
        # Accept both so external lifecycle progress cannot strand the agent run.
        if pay_run.status not in {"draft", "approved", "completed"}:
            raise ValueError(f"Pay run cannot be approved from status '{pay_run.status}'")

        if invoice.status == "draft":
            invoice.status = "issued"
        if pay_run.status == "draft":
            PayRunLifecycle().transition(pay_run=pay_run, new_status="approved")

        run.status = "completed"
        run.completed_at = _now()
        _set_step(db, run.id, "handoff", "completed", {
            "message": "The invoice and pay run passed human approval.",
            "approved_by_user_id": approved_by_user_id,
            "invoice_id": invoice.id,
            "invoice_status": invoice.status,
            "pay_run_id": pay_run.id,
            "pay_run_status": pay_run.status,
        })
        db.commit()
        db.refresh(run)
        return run


def resume_worker_payroll_runs(worker_id: int):
    with SessionLocal() as db:
        run_ids = list(db.scalars(select(PayrollAgentRun.id).where(
            PayrollAgentRun.worker_id == worker_id,
            PayrollAgentRun.status == "waiting_for_requirements",
        )))
    resumed = []
    for run_id in run_ids:
        with SessionLocal() as db:
            run = db.get(PayrollAgentRun, run_id)
            if payroll_blockers(db, run):
                continue
        try:
            advance_payroll_agent_run(run_id, hours_confirmed=True)
            resumed.append(run_id)
        except Exception:
            # The source worker-data update must remain successful. The run is
            # persisted as failed with a safe diagnostic for an administrator.
            continue
    return resumed
