from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_action import AgentAction
from app.models.agent_run import AgentRun
from app.models.agent_task import AgentTask
from app.models.engagement import Engagement
from app.models.notification import Notification
from app.models.user import User
from app.tfn_declaration_agent import missing_tfn_declaration_alert
from app.worker_compliance_service import missing_payroll_setup_items


AGENT_NAME = "green_orbit_timesheet_agent"


def process_timesheet_created(
    db: Session, *, engagement_id: int, as_of: date,
    assignment_id: int | None = None,
    timesheet_header_id: int | None = None,
    event_type: str = "timesheet_created",
    request_popup: bool = True,
) -> dict | None:
    """Reconcile the timesheet-created event into durable agent state."""
    engagement = db.get(Engagement, engagement_id)
    worker_id = engagement.worker_id if engagement else None
    run = AgentRun(
        agent_name=AGENT_NAME,
        event_type=event_type,
        status="running",
        input_data={
            "engagement_id": engagement_id,
            "assignment_id": assignment_id,
            "timesheet_header_id": timesheet_header_id,
            "as_of": as_of.isoformat(),
        },
        output_data={},
    )
    db.add(run)
    db.flush()

    alert = missing_tfn_declaration_alert(db, engagement_id, as_of=as_of)
    fingerprint = f"missing_tfn_declaration:worker:{worker_id}"
    task = db.scalar(select(AgentTask).where(
        AgentTask.agent_name == AGENT_NAME,
        AgentTask.fingerprint == fingerprint,
    ).order_by(AgentTask.id.desc()).limit(1))

    if alert:
        if task is None:
            task = AgentTask(
                agent_name=AGENT_NAME,
                issue_code="missing_tfn_declaration",
                fingerprint=fingerprint,
                status="waiting_for_human",
                priority="critical",
                title="TFN declaration requires attention",
                summary=alert["content"],
                worker_id=worker_id,
                engagement_id=engagement_id,
                assignment_id=assignment_id,
                timesheet_header_id=timesheet_header_id,
                task_context={"first_seen_as_of": as_of.isoformat()},
            )
            db.add(task)
            db.flush()
            action_type = "task_created"
        else:
            task.status = "waiting_for_human"
            task.resolved_at = None
            task.assignment_id = assignment_id or task.assignment_id
            task.timesheet_header_id = timesheet_header_id or task.timesheet_header_id
            action_type = "task_reconfirmed"
        db.add(AgentAction(
            task_id=task.id, run_id=run.id, action_type=action_type,
            status="completed", details={"popup_requested": request_popup},
        ))
        run.status = "completed"
        run.output_data = {"task_id": task.id, "issue_code": alert["code"]}
    else:
        if task is not None:
            task.status = "resolved"
            task.resolved_at = datetime.now(timezone.utc)
            db.add(AgentAction(
                task_id=task.id, run_id=run.id, action_type="task_resolved",
                status="completed", details={"verified": True},
            ))
        run.status = "completed"
        run.output_data = {"ready": True, "resolved_task_id": task.id if task else None}
    run.completed_at = datetime.now(timezone.utc)

    if worker_id is not None:
        missing_items = missing_payroll_setup_items(db, worker_id, as_of=as_of)
        portal_user = db.scalar(select(User).where(
            User.worker_id == worker_id,
            User.role == "worker",
            User.is_active.is_(True),
        ).limit(1))
        if missing_items and portal_user is not None:
            existing_message = db.scalar(select(Notification.id).where(
                Notification.recipient_user_id == portal_user.id,
                Notification.notification_type == "agent_payroll_setup_required",
            ).limit(1))
            if existing_message is None:
                labels = [item["title"] for item in missing_items]
                if len(labels) == 1:
                    missing_label = labels[0]
                else:
                    missing_label = f"{', '.join(labels[:-1])} and {labels[-1]}"
                db.add(Notification(
                    recipient_user_id=portal_user.id,
                    notification_type="agent_payroll_setup_required",
                    title="Action required: complete your payroll setup",
                    message=(
                        f"The Green Orbit agent found that your {missing_label} "
                        "is missing. Please use the secure payroll setup checklist to provide it."
                    ),
                    action_url="/portal#payroll-setup",
                ))
                if task is not None:
                    db.add(AgentAction(
                        task_id=task.id,
                        run_id=run.id,
                        action_type="worker_notified",
                        status="completed",
                        details={
                            "channel": "worker_portal",
                            "issue_codes": [item["code"] for item in missing_items],
                        },
                    ))
    db.flush()
    return alert
