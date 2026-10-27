import json
import logging
import os
from concurrent.futures import TimeoutError

from dotenv import load_dotenv
from google.cloud import pubsub_v1

load_dotenv()

from app.document_processor import process_storage_object


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _storage_event(message) -> tuple[str, str]:
    bucket = message.attributes.get("bucketId")
    object_name = message.attributes.get("objectId")
    if not bucket or not object_name:
        payload = json.loads(message.data.decode("utf-8"))
        bucket = bucket or payload.get("bucket") or payload.get("bucketId")
        object_name = object_name or payload.get("name") or payload.get("objectId")
    if not bucket or not object_name:
        raise ValueError("Pub/Sub message does not identify a storage object")
    return bucket, object_name


def run() -> None:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    subscription = os.environ["DOCUMENT_PROCESSING_SUBSCRIPTION"]
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(project, subscription)

    def callback(message) -> None:
        try:
            bucket, object_name = _storage_event(message)
            outcome = process_storage_object(bucket, object_name)
            logger.info("Document event %s: %s", message.message_id, outcome)
            message.ack()
        except Exception:
            logger.exception("Document event %s failed", message.message_id)
            message.nack()

    future = subscriber.subscribe(subscription_path, callback=callback)
    logger.info("Listening on %s", subscription_path)
    try:
        future.result()
    except KeyboardInterrupt:
        future.cancel()
        try:
            future.result(timeout=30)
        except (TimeoutError, KeyboardInterrupt):
            pass
    finally:
        subscriber.close()


if __name__ == "__main__":
    run()
