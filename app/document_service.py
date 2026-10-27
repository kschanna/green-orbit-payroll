from datetime import date
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.document_storage import DocumentStorage
from app.models.worker_document import WorkerDocument


DOCUMENT_TYPES = {
    "tfn_declaration": "TFN declaration",
    "super_choice": "Super choice declaration",
    "contractor_insurance": "Contractor insurance",
    "identity": "Identity document",
    "other": "Other",
}
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class DocumentValidationError(ValueError):
    pass


def validate_pdf(filename: str | None, content_type: str | None, content: bytes) -> str:
    safe_name = Path(filename or "document.pdf").name
    if not safe_name.lower().endswith(".pdf"):
        raise DocumentValidationError("Only PDF documents can be uploaded")
    if content_type not in {"application/pdf", "application/octet-stream"}:
        raise DocumentValidationError("Only PDF documents can be uploaded")
    if not content.startswith(b"%PDF-"):
        raise DocumentValidationError("The uploaded file is not a valid PDF")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentValidationError("Documents must be 10 MB or smaller")
    return safe_name[:255]


class DocumentService:
    @staticmethod
    def list_for_worker(db: Session, worker_id: int) -> list[WorkerDocument]:
        return list(
            db.scalars(
                select(WorkerDocument)
                .where(WorkerDocument.worker_id == worker_id)
                .order_by(WorkerDocument.created_at.desc(), WorkerDocument.id.desc())
            ).all()
        )

    @staticmethod
    def create(
        db: Session,
        storage: DocumentStorage,
        *,
        worker_id: int,
        user_id: int,
        document_type: str,
        filename: str | None,
        content_type: str | None,
        content: bytes,
        issued_on: date | None = None,
        expires_on: date | None = None,
    ) -> WorkerDocument:
        if document_type not in DOCUMENT_TYPES:
            raise DocumentValidationError("Unsupported document type")
        if expires_on and issued_on and expires_on < issued_on:
            raise DocumentValidationError("Expiry date cannot precede issue date")

        safe_name = validate_pdf(filename, content_type, content)
        storage_key = f"workers/{worker_id}/documents/{uuid4()}/original.pdf"
        storage.put(storage_key, content, "application/pdf")

        document = WorkerDocument(
            worker_id=worker_id,
            uploaded_by_user_id=user_id,
            document_type=document_type,
            original_filename=safe_name,
            content_type="application/pdf",
            size_bytes=len(content),
            storage_key=storage_key,
            status="uploaded",
            issued_on=issued_on,
            expires_on=expires_on,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document
