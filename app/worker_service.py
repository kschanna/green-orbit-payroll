
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.worker import Worker


class WorkerError(ValueError):
    pass


class WorkerService:

    @staticmethod
    def create(db: Session, first_name: str, last_name: str,
               email: str, phone: str | None = None):

        first_name = first_name.strip()
        last_name = last_name.strip()
        email = email.strip().lower()
        phone = (phone or "").strip() or None

        if not first_name or not last_name or not email:
            raise WorkerError("First name, last name and email are required.")

        existing = db.scalar(
            select(Worker).where(func.lower(Worker.email) == email)
        )

        if existing:
            raise WorkerError(
                f"Worker #{existing.id} already uses this email."
            )

        worker = Worker(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            active=True,
        )

        db.add(worker)
        db.commit()
        db.refresh(worker)

        return worker

    @staticmethod
    def get(db: Session, worker_id: int):
        return db.get(Worker, worker_id)

    @staticmethod
    def list(db: Session, search: str = ""):
        statement = select(Worker)

        if search.strip():
            term = f"%{search.strip()}%"

            statement = statement.where(
                or_(
                    Worker.first_name.ilike(term),
                    Worker.last_name.ilike(term),
                    Worker.email.ilike(term),
                )
            )

        statement = statement.order_by(
            Worker.id.desc()
        )

        return list(db.scalars(statement).all())

    @staticmethod
    def update(db: Session, worker: Worker,
               first_name: str, last_name: str,
               email: str, phone: str | None = None):

        first_name = first_name.strip()
        last_name = last_name.strip()
        email = email.strip().lower()

        if not first_name or not last_name or not email:
            raise WorkerError("First name, last name and email are required.")

        existing = db.scalar(
            select(Worker).where(
                func.lower(Worker.email) == email,
                Worker.id != worker.id,
            )
        )

        if existing:
            raise WorkerError(
                f"Worker #{existing.id} already uses this email."
            )

        worker.first_name = first_name
        worker.last_name = last_name
        worker.email = email
        worker.phone = (phone or "").strip() or None

        db.commit()
        db.refresh(worker)

        return worker

    @staticmethod
    def set_active(db: Session, worker: Worker, active: bool):
        worker.active = active
        db.commit()
        db.refresh(worker)

        return worker
