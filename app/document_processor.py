import logging
import os
from decimal import Decimal

from google.cloud import documentai
from google.protobuf.json_format import MessageToDict
from sqlalchemy import select

from app.database import SessionLocal
from app.document_service import DOCUMENT_TYPES
from app.document_storage import get_document_storage
from app.models.document_extraction import DocumentExtraction
from app.models.notification import Notification
from app.models.user import User  # Registers document audit foreign-key target.
from app.models.worker import Worker  # Registers Engagement's relationship target.
from app.models.worker_document import WorkerDocument


logger = logging.getLogger(__name__)


def _field_text(layout, full_text: str) -> str:
    anchor = layout.text_anchor
    return "".join(
        full_text[int(segment.start_index or 0):int(segment.end_index)]
        for segment in anchor.text_segments
    ).strip()


def _form_values(document) -> tuple[dict, list[float]]:
    values: dict[str, str] = {}
    confidences: list[float] = []
    for page in document.pages:
        for field in page.form_fields:
            name = _field_text(field.field_name, document.text).rstrip(":").strip()
            value = _field_text(field.field_value, document.text)
            if name:
                values[name] = value
                confidences.append(float(field.field_value.confidence or 0))
    return values, confidences


def process_storage_object(bucket: str, object_name: str) -> str:
    expected_bucket = os.environ["DOCUMENT_BUCKET"]
    if bucket != expected_bucket:
        raise ValueError("Ignoring event from an unexpected bucket")

    with SessionLocal() as db:
        worker_document = db.scalar(
            select(WorkerDocument).where(WorkerDocument.storage_key == object_name)
        )
        if worker_document is None:
            raise LookupError(f"No document record exists for {object_name}")
        if worker_document.status in {"ready_for_review", "approved", "rejected"}:
            return "already_processed"
        worker_document.status = "processing"
        worker_document.error_message = None
        db.commit()
        document_id = worker_document.id

    try:
        content = get_document_storage().get(object_name)
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.getenv("DOCUMENT_AI_LOCATION", "australia-southeast1")
        processor_id = os.environ["DOCUMENT_AI_PROCESSOR_ID"]
        client = documentai.DocumentProcessorServiceClient(
            client_options={"api_endpoint": f"{location}-documentai.googleapis.com"}
        )
        processor_name = client.processor_path(project, location, processor_id)
        result = client.process_document(
            request=documentai.ProcessRequest(
                name=processor_name,
                raw_document=documentai.RawDocument(
                    content=content,
                    mime_type="application/pdf",
                ),
            )
        )
        proposed_values, confidences = _form_values(result.document)
        confidence = (
            Decimal(str(sum(confidences) / len(confidences))).quantize(Decimal("0.0001"))
            if confidences else None
        )
        warnings = [] if proposed_values else ["No form fields were detected"]
        raw_result = MessageToDict(
            result.document._pb,
            preserving_proto_field_name=True,
        )

        with SessionLocal() as db:
            worker_document = db.get(WorkerDocument, document_id)
            extraction = db.scalar(
                select(DocumentExtraction).where(
                    DocumentExtraction.document_id == document_id
                )
            )
            if extraction is None:
                extraction = DocumentExtraction(
                    document_id=document_id,
                    provider="google_document_ai",
                )
                db.add(extraction)
            extraction.processor_name = processor_name
            extraction.raw_result = raw_result
            extraction.proposed_values = proposed_values
            extraction.confidence = confidence
            extraction.warnings = warnings
            extraction.error_message = None
            worker_document.status = "ready_for_review"
            worker_document.error_message = None
            worker = db.get(Worker, worker_document.worker_id)
            worker_name = (
                f"{worker.first_name} {worker.last_name}"
                if worker is not None else f"Worker #{worker_document.worker_id}"
            )
            document_label = DOCUMENT_TYPES.get(
                worker_document.document_type,
                worker_document.document_type.replace("_", " ").title(),
            )
            admin_user_ids = db.scalars(
                select(User.id).where(User.role == "admin", User.is_active.is_(True))
            ).all()
            recipients = admin_user_ids or [None]
            db.add_all(
                [Notification(
                    recipient_user_id=recipient_user_id,
                    notification_type="document_ready_for_review",
                    title=f"{worker_name} uploaded a document",
                    message=(
                        f"{worker_name}'s {document_label} has been processed "
                        "and is ready for review and validation."
                    ),
                    action_url=(
                        f"/ui/workers/{worker_document.worker_id}/documents/"
                        f"{worker_document.id}/review"
                    ),
                ) for recipient_user_id in recipients]
            )
            db.commit()
        return "processed"
    except Exception as exc:
        logger.exception("Document processing failed for document %s", document_id)
        with SessionLocal() as db:
            worker_document = db.get(WorkerDocument, document_id)
            if worker_document is not None:
                worker_document.status = "failed"
                worker_document.error_message = str(exc)[:2000]
                db.commit()
        raise
