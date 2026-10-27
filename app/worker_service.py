
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.employee_tax_profile import EmployeeTaxProfile


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
    def _list_statement(
        search: str = "", active_status: str = "all",
        tax_free: str = "all", engagement_type: str = "all",
    ):
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

        if active_status == "active":
            statement = statement.where(Worker.active.is_(True))
        elif active_status == "inactive":
            statement = statement.where(Worker.active.is_(False))

        tax_free_profile = select(EmployeeTaxProfile.id).where(
            EmployeeTaxProfile.worker_id == Worker.id,
            EmployeeTaxProfile.claims_tax_free_threshold.is_(True),
        ).exists()
        if tax_free == "claimed":
            statement = statement.where(tax_free_profile)
        elif tax_free == "not_claimed":
            statement = statement.where(~tax_free_profile)

        if engagement_type in {
            "payg_employee", "payg_contractor", "company_contractor"
        }:
            statement = statement.where(select(Engagement.id).where(
                Engagement.worker_id == Worker.id,
                Engagement.engagement_type == engagement_type,
            ).exists())

        return statement

    @staticmethod
    def list(
        db: Session, search: str = "", offset: int = 0,
        limit: int | None = None, active_status: str = "all",
        tax_free: str = "all", engagement_type: str = "all",
    ):
        statement = WorkerService._list_statement(
            search, active_status, tax_free, engagement_type
        ).order_by(
            Worker.id.desc()
        ).offset(offset)

        if limit is not None:
            statement = statement.limit(limit)

        return list(db.scalars(statement).all())

    @staticmethod
    def count(
        db: Session, search: str = "", active_status: str = "all",
        tax_free: str = "all", engagement_type: str = "all",
    ) -> int:
        statement = WorkerService._list_statement(
            search, active_status, tax_free, engagement_type
        ).with_only_columns(
            func.count(Worker.id)
        ).order_by(None)
        return int(db.scalar(statement) or 0)

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

    @staticmethod
    def delete(db: Session, worker: Worker):
        """Permanently delete a worker that has no dependent records."""
        worker_id = worker.id
        db.delete(worker)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise WorkerError(
                "This worker has payroll or engagement records and cannot be "
                "deleted. Deactivate the worker instead."
            ) from exc

        return worker_id
