from datetime import date

from app.database import SessionLocal
from app.models.pay_run import PayRun


def main():
    with SessionLocal() as session:

        pay_run = PayRun(
            organisation_id=1,
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 14),
            payment_date=date(2026, 10, 15),
            status="draft"
        )

        session.add(pay_run)
        session.commit()

        print(f"Pay Run created with ID: {pay_run.id}")
        print(f"Status: {pay_run.status}")


if __name__ == "__main__":
    main()