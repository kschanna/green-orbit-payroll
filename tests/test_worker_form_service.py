from cryptography.fernet import Fernet
from fastapi import HTTPException
import pytest

from app.worker_form_service import (
    FORM_SCHEMAS, declaration_hash, decrypt_payload, encrypt_payload,
    validate_submission,
)


def test_tfn_form_is_schema_driven_validated_and_encrypted(monkeypatch):
    monkeypatch.setenv("GREEN_ORBIT_TFN_KEY", Fernet.generate_key().decode())
    raw = {
        "tfn": "123 456 782",
        "residency_status": "resident",
        "claims_tax_free_threshold": "yes",
        "has_study_loan": "no",
        "signature_name": "Test Worker",
        "accepted": "on",
    }
    values = validate_submission("tfn_declaration", raw)
    encrypted = encrypt_payload(values)

    assert FORM_SCHEMAS["tfn_declaration"]["version"] == "1.0"
    assert values["tfn"] == "123456782"
    assert b"123456782" not in encrypted
    assert decrypt_payload(encrypted) == values
    assert len(declaration_hash("tfn_declaration", "1.0", values)) == 64


def test_tfn_form_rejects_invalid_tfn():
    with pytest.raises(HTTPException, match="valid Australian TFN"):
        validate_submission("tfn_declaration", {
            "tfn": "123456789", "residency_status": "resident",
            "claims_tax_free_threshold": "yes", "has_study_loan": "no",
            "signature_name": "Test Worker", "accepted": "on",
        })


def test_smsf_form_requires_valid_abn():
    with pytest.raises(HTTPException, match="11-digit SMSF ABN"):
        validate_submission("super_choice", {
            "fund_type": "smsf", "fund_name": "Test SMSF", "fund_usi": "ESA",
            "member_number": "M123", "fund_abn": "123",
            "signature_name": "Test Worker", "accepted": "on",
        })
