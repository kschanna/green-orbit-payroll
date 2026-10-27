import os
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv


load_dotenv()


class DocumentStorage(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class LocalDocumentStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid document storage key")
        return path

    def put(self, key: str, content: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class GcsDocumentStorage:
    def __init__(self, bucket_name: str):
        from google.cloud import storage

        self.bucket = storage.Client().bucket(bucket_name)

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.bucket.blob(key).upload_from_string(content, content_type=content_type)

    def get(self, key: str) -> bytes:
        return self.bucket.blob(key).download_as_bytes()

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self.bucket.blob(key).delete()
        except NotFound:
            pass


def get_document_storage() -> DocumentStorage:
    bucket = os.getenv("DOCUMENT_BUCKET")
    if bucket:
        return GcsDocumentStorage(bucket)
    return LocalDocumentStorage(os.getenv("DOCUMENT_STORAGE_PATH", ".local/documents"))
