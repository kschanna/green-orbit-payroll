from pathlib import Path

import pytest

from app.document_service import DocumentValidationError, validate_pdf
from app.document_storage import LocalDocumentStorage
from app.worker_documents_router import middle_ellipsis, router
from app.document_profile_service import redact_sensitive_values, review_values


def test_worker_document_routes_registered():
    expected = {
        ("/ui/workers/{worker_id}/documents", "GET"),
        ("/ui/workers/{worker_id}/documents", "POST"),
        ("/ui/workers/{worker_id}/documents/{document_id}/download", "GET"),
        ("/ui/workers/{worker_id}/documents/{document_id}/delete", "POST"),
        ("/ui/workers/{worker_id}/documents/{document_id}/review", "GET"),
        ("/ui/workers/{worker_id}/documents/{document_id}/review", "POST"),
        ("/ui/notifications", "GET"),
        ("/ui/notifications/{notification_id}/open", "GET"),
        ("/ui/notifications/read-all", "POST"),
    }
    actual = {
        (route.path, method)
        for route in router.routes
        for method in route.methods
    }
    assert expected <= actual


def test_validate_pdf_accepts_a_pdf():
    assert validate_pdf("declaration.PDF", "application/pdf", b"%PDF-1.7\n") == "declaration.PDF"


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("declaration.exe", "application/pdf", b"%PDF-1.7\n"),
        ("declaration.pdf", "text/plain", b"%PDF-1.7\n"),
        ("declaration.pdf", "application/pdf", b"not a PDF"),
    ],
)
def test_validate_pdf_rejects_invalid_uploads(filename, content_type, content):
    with pytest.raises(DocumentValidationError):
        validate_pdf(filename, content_type, content)


def test_local_storage_round_trip_and_containment(tmp_path: Path):
    storage = LocalDocumentStorage(tmp_path)
    storage.put("workers/1/documents/abc/original.pdf", b"%PDF-test", "application/pdf")
    assert storage.get("workers/1/documents/abc/original.pdf") == b"%PDF-test"
    storage.delete("workers/1/documents/abc/original.pdf")
    assert not (tmp_path / "workers/1/documents/abc/original.pdf").exists()
    storage.delete("workers/1/documents/abc/original.pdf")

    with pytest.raises(ValueError):
        storage.put("../outside.pdf", b"bad", "application/pdf")


def test_middle_ellipsis_preserves_start_end_and_limit():
    filename = "a-very-long-worker-document-name-with-important-ending.pdf"
    shortened = middle_ellipsis(filename, 30)

    assert shortened.startswith("a-very-long-wo")
    assert "..." in shortened
    assert shortened.endswith("nt-ending.pdf")
    assert len(shortened) == 30


def test_middle_ellipsis_leaves_short_names_unchanged():
    assert middle_ellipsis("short.pdf", 30) == "short.pdf"


def test_tfn_review_adds_missing_payroll_fields():
    values = review_values("tfn_declaration", {"Date signed": "26 October 2026"})

    assert values["Tax file number"] == ""
    assert values["Residency status"] == ""
    assert values["Effective from"] == ""


def test_super_review_preserves_extracted_fields_and_adds_effective_date():
    values = review_values("super_choice", {"Fund name": "Example Fund"})

    assert values["Fund name"] == "Example Fund"
    assert values["Fund USI"] == ""
    assert values["Effective from"] == ""


def test_approved_tfn_is_redacted_before_review_is_saved():
    values = redact_sensitive_values("tfn_declaration", {"Tax file number": "123 456 782"})

    assert values["Tax file number"] == "*** *** 782"
