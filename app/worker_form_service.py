import hashlib
import json
from datetime import date

from fastapi import HTTPException

from app.tfn_security import canonical_tfn, get_cipher


FORM_SCHEMAS = {
    "tfn_declaration": {
        "version": "1.0",
        "title": "TFN declaration",
        "description": "Provide your tax declaration securely for payroll review.",
        "fields": [
            {"name": "tfn", "label": "Tax file number", "type": "password", "required": True, "sensitive": True, "help": "Your TFN is encrypted before it is stored."},
            {"name": "residency_status", "label": "Residency status", "type": "select", "required": True, "options": [["resident", "Australian resident"], ["foreign_resident", "Foreign resident"], ["working_holiday_maker", "Working holiday maker"]]},
            {"name": "claims_tax_free_threshold", "label": "Claim the tax-free threshold?", "type": "select", "required": True, "options": [["yes", "Yes"], ["no", "No"]]},
            {"name": "has_study_loan", "label": "Do you have a HELP, VSL, FS, SSL or TSL debt?", "type": "select", "required": True, "options": [["yes", "Yes"], ["no", "No"]]},
            {"name": "signature_name", "label": "Type your full legal name", "type": "text", "required": True},
            {"name": "accepted", "label": "I declare that the information provided is true and correct.", "type": "checkbox", "required": True},
        ],
    },
    "super_choice": {
        "version": "1.0",
        "title": "Super choice form",
        "description": "Nominate the super fund where employer contributions should be paid.",
        "fields": [
            {"name": "fund_type", "label": "Fund type", "type": "select", "required": True, "options": [["apra", "APRA-regulated fund"], ["smsf", "Self-managed super fund (SMSF)"]]},
            {"name": "fund_name", "label": "Fund name", "type": "text", "required": True},
            {"name": "fund_usi", "label": "Fund USI or SMSF electronic service address", "type": "text", "required": True},
            {"name": "member_number", "label": "Member or account number", "type": "text", "required": True, "sensitive": True},
            {"name": "fund_abn", "label": "SMSF ABN", "type": "text", "required": True, "show_when": {"field": "fund_type", "value": "smsf"}},
            {"name": "signature_name", "label": "Type your full legal name", "type": "text", "required": True},
            {"name": "accepted", "label": "I declare that this is my chosen super fund.", "type": "checkbox", "required": True},
        ],
    },
}


def validate_submission(form_type: str, raw: dict[str, str]) -> dict[str, str]:
    schema = FORM_SCHEMAS.get(form_type)
    if schema is None:
        raise HTTPException(404, "Payroll form not found")
    values = {key: str(value).strip() for key, value in raw.items()}
    missing = []
    for field in schema["fields"]:
        condition = field.get("show_when")
        active = not condition or values.get(condition["field"]) == condition["value"]
        if active and field.get("required") and not values.get(field["name"]):
            missing.append(field["label"])
        if field["type"] == "select" and values.get(field["name"]):
            allowed = {item[0] for item in field["options"]}
            if values[field["name"]] not in allowed:
                raise HTTPException(422, f"Invalid value for {field['label']}")
    if missing:
        raise HTTPException(422, f"Complete these fields: {', '.join(missing)}")
    if values.get("accepted") != "on":
        raise HTTPException(422, "You must accept the declaration")
    if form_type == "tfn_declaration":
        try:
            values["tfn"] = canonical_tfn(values["tfn"])
        except ValueError as exc:
            raise HTTPException(422, "Enter a valid Australian TFN") from exc
    if form_type == "super_choice" and values.get("fund_type") == "smsf":
        abn = values.get("fund_abn", "").replace(" ", "")
        if len(abn) != 11 or not abn.isdigit():
            raise HTTPException(422, "Enter a valid 11-digit SMSF ABN")
        values["fund_abn"] = abn
    return values


def encrypt_payload(values: dict[str, str]) -> bytes:
    return get_cipher().encrypt(json.dumps(values, sort_keys=True).encode())


def decrypt_payload(payload: bytes) -> dict[str, str]:
    return json.loads(get_cipher().decrypt(payload).decode())


def declaration_hash(form_type: str, schema_version: str, values: dict[str, str]) -> str:
    material = {"form_type": form_type, "schema_version": schema_version, "values": values}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def approval_values(form_type: str, values: dict[str, str]) -> dict[str, str]:
    if form_type == "tfn_declaration":
        return {
            "Tax file number": values["tfn"],
            "Residency status": values["residency_status"],
            "Claims tax-free threshold": values["claims_tax_free_threshold"],
            "Has study loan": values["has_study_loan"],
            "Effective from": date.today().isoformat(),
        }
    return {
        "Fund name": values["fund_name"],
        "Fund USI": values["fund_usi"],
        "Member number": values["member_number"],
        "Effective from": date.today().isoformat(),
    }
