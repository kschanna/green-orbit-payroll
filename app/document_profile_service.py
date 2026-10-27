import re
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.employee_tfn import EmployeeTFN
from app.models.employee_tfn_audit import EmployeeTFNAudit
from app.tfn_security import canonical_tfn, encrypt_tfn


TFN_FIELDS = {
    "Tax file number": "",
    "Residency status": "",
    "Claims tax-free threshold": "",
    "Has study loan": "",
    "Effective from": "",
}
SUPER_FIELDS = {
    "Fund name": "",
    "Fund USI": "",
    "Member number": "",
    "Effective from": "",
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _find(values: dict, *aliases: str) -> str:
    normalised = {_key(str(name)): str(value).strip() for name, value in values.items()}
    return next(
        (normalised[_key(alias)] for alias in aliases if normalised.get(_key(alias))),
        "",
    )


def _parse_bool(value: str, label: str) -> bool:
    normalised = value.strip().lower()
    if normalised in {"yes", "y", "true", "1", "checked", "selected"}:
        return True
    if normalised in {"no", "n", "false", "0", "unchecked", "not selected"}:
        return False
    raise HTTPException(422, f"{label} must be Yes or No")


def _parse_date(value: str, label: str) -> date:
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    raise HTTPException(422, f"{label} must be a valid date")


def review_values(document_type: str, values: dict) -> dict:
    """Add canonical payroll fields without discarding other OCR output."""
    result = dict(values or {})
    required = TFN_FIELDS if document_type == "tfn_declaration" else (
        SUPER_FIELDS if document_type == "super_choice" else {}
    )
    existing = {_key(str(name)) for name in result}
    for name, default in required.items():
        if _key(name) not in existing:
            result[name] = default
    return result


def redact_sensitive_values(document_type: str, values: dict) -> dict:
    result = dict(values)
    if document_type != "tfn_declaration":
        return result
    for name, value in result.items():
        if _key(str(name)) in {"tax file number", "tfn"} and value:
            digits = canonical_tfn(str(value))
            result[name] = f"*** *** {digits[-3:]}"
    return result


def apply_document_values(
    db: Session, *, document_type: str, worker_id: int,
    actor_user_id: int, values: dict,
) -> str | None:
    if document_type == "tfn_declaration":
        return _apply_tfn(db, worker_id, actor_user_id, values)
    if document_type == "super_choice":
        return _apply_super(db, worker_id, values)
    return None


def _apply_tfn(db: Session, worker_id: int, actor_user_id: int, values: dict) -> str:
    raw_tfn = _find(values, "Tax file number", "TFN")
    residency = _find(values, "Residency status", "Tax residency status").lower().replace(" ", "_")
    threshold = _find(values, "Claims tax-free threshold", "Claim tax free threshold")
    study_loan = _find(values, "Has study loan", "Study loan", "HELP debt", "HECS debt")
    effective_text = _find(values, "Effective from", "Date signed", "Declaration date")
    missing = [label for label, value in (
        ("Tax file number", raw_tfn), ("Residency status", residency),
        ("Claims tax-free threshold", threshold), ("Has study loan", study_loan),
        ("Effective from", effective_text),
    ) if not value]
    if missing:
        raise HTTPException(422, f"Complete these TFN fields before approval: {', '.join(missing)}")
    if residency not in {"resident", "foreign_resident", "working_holiday_maker"}:
        raise HTTPException(422, "Residency status must be resident, foreign resident, or working holiday maker")
    try:
        digits = canonical_tfn(raw_tfn)
        ciphertext = encrypt_tfn(digits)
    except ValueError as exc:
        raise HTTPException(422, "Tax file number is not a valid Australian TFN") from exc
    except RuntimeError as exc:
        raise HTTPException(503, "TFN encryption is not configured") from exc

    effective_from = _parse_date(effective_text, "Effective from")
    profile = db.scalar(select(EmployeeTaxProfile).where(
        EmployeeTaxProfile.worker_id == worker_id,
        EmployeeTaxProfile.effective_to.is_(None),
    ).order_by(EmployeeTaxProfile.effective_from.desc()).limit(1))
    if profile is None:
        profile = EmployeeTaxProfile(worker_id=worker_id, employee_id=None, engagement_id=None)
        db.add(profile)
    profile.residency_status = residency
    profile.claims_tax_free_threshold = _parse_bool(threshold, "Claims tax-free threshold")
    profile.has_study_loan = _parse_bool(study_loan, "Has study loan")
    profile.tfn_declaration_received = True
    profile.effective_from = effective_from
    profile.effective_to = None

    record = db.get(EmployeeTFN, worker_id)
    action = "updated" if record else "created"
    if record is None:
        record = EmployeeTFN(worker_id=worker_id, employee_id=None, engagement_id=None,
                             encrypted_tfn=ciphertext, last_three=digits[-3:])
        db.add(record)
    else:
        record.encrypted_tfn = ciphertext
        record.last_three = digits[-3:]
    db.add(EmployeeTFNAudit(worker_id=worker_id, employee_id=None, engagement_id=None,
                            actor_user_id=actor_user_id, action=f"document_{action}"))
    return "Tax and encrypted TFN records updated"


def _apply_super(db: Session, worker_id: int, values: dict) -> str:
    fund_name = _find(values, "Fund name", "Super fund name")
    fund_usi = _find(values, "Fund USI", "USI", "Unique superannuation identifier")
    member_number = _find(values, "Member number", "Membership number", "Account number")
    effective_text = _find(values, "Effective from", "Date signed", "Declaration date")
    missing = [label for label, value in (
        ("Fund name", fund_name), ("Fund USI", fund_usi),
        ("Member number", member_number), ("Effective from", effective_text),
    ) if not value]
    if missing:
        raise HTTPException(422, f"Complete these super fields before approval: {', '.join(missing)}")

    profile = db.scalar(select(EmployeeSuperProfile).where(
        EmployeeSuperProfile.worker_id == worker_id,
        EmployeeSuperProfile.effective_to.is_(None),
    ).order_by(EmployeeSuperProfile.effective_from.desc()).limit(1))
    if profile is None:
        profile = EmployeeSuperProfile(worker_id=worker_id, employee_id=None, engagement_id=None)
        db.add(profile)
    profile.fund_name = fund_name
    profile.fund_usi = fund_usi
    profile.member_number = member_number
    profile.effective_from = _parse_date(effective_text, "Effective from")
    profile.effective_to = None
    return "Superannuation record updated"
