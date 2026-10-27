import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.document_worker import run


@asynccontextmanager
async def lifespan(_app: FastAPI):
    listener = threading.Thread(
        target=run,
        name="document-pubsub-listener",
        daemon=True,
    )
    listener.start()
    yield


app = FastAPI(title="Green Orbit Document Listener", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "healthy"}
