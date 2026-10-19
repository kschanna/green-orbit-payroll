from app.engagement_resolver import resolve_engagement_id, resolve_worker_id
import hmac
import os

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.database import SessionLocal
from app.models.employee_tfn import EmployeeTFN
from app.models.employee_tfn_audit import EmployeeTFNAudit
from app.tfn_security import canonical_tfn, encrypt_tfn


router = APIRouter()


def require_tfn_admin(request: Request) -> int:
    user_id = request.session.get("user_id")

    if not isinstance(user_id, int):
        raise HTTPException(401, "Authentication required")

    configured = os.environ.get(
        "GREEN_ORBIT_TFN_ADMIN_USER_IDS", ""
    )

    allowed = {
        int(value.strip())
        for value in configured.split(",")
        if value.strip().isdigit()
    }

    if user_id not in allowed:
        raise HTTPException(403, "TFN access denied")

    return user_id


def require_csrf(request: Request, supplied: str):
    expected = request.session.get("csrf_token", "")

    if (
        not expected
        or not supplied
        or not hmac.compare_digest(expected, supplied)
    ):
        raise HTTPException(403, "Invalid CSRF token")




# Worker-native encrypted TFN administration.
from app.models.worker import Worker


@router.post("/ui/workers/{worker_id}/tfn")
def save_worker_tfn(
    request: Request,
    worker_id: int,
    tfn: str = Form(...),
    csrf_token: str = Form(...),
):
    actor_id = require_tfn_admin(request)
    require_csrf(request, csrf_token)

    try:
        digits = canonical_tfn(tfn)
        ciphertext = encrypt_tfn(digits)
    except ValueError:
        raise HTTPException(422, "Invalid Australian TFN")
    except RuntimeError:
        raise HTTPException(503, "TFN encryption unavailable")

    with SessionLocal() as db:
        if db.get(Worker, worker_id) is None:
            raise HTTPException(404, "Worker not found")

        record = db.execute(
            select(EmployeeTFN)
            .where(EmployeeTFN.worker_id == worker_id)
            .with_for_update()
        ).scalar_one_or_none()

        action = "updated" if record else "created"

        if record is None:
            record = EmployeeTFN(
                worker_id=worker_id,
                employee_id=None,
                engagement_id=None,
                encrypted_tfn=ciphertext,
                last_three=digits[-3:],
            )
            db.add(record)
        else:
            record.encrypted_tfn = ciphertext
            record.last_three = digits[-3:]

        db.add(
            EmployeeTFNAudit(
                worker_id=worker_id,
                employee_id=None,
                engagement_id=None,
                actor_user_id=actor_id,
                action=action,
            )
        )

        db.commit()

    return RedirectResponse(
        f"/ui/workers/{worker_id}/tax",
        status_code=303,
    )
