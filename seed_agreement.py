from datetime import date
from decimal import Decimal

from app.database import SessionLocal
from app.models.employment_agreement import EmploymentAgreement


def main():
    with SessionLocal() as session:
        agreement = EmploymentAgreement(
            employee_id=1,
            employment_type="full_time",
            pay_basis="hourly",
            hourly_rate=Decimal("45.00"),
            ordinary_hours_per_week=Decimal("38.00"),
            pay_frequency="fortnightly",
            start_date=date(2026, 10, 1),
            end_date=None
        )

        session.add(agreement)
        session.commit()

        print(f"Agreement created with ID: {agreement.id}")


if __name__ == "__main__":
    main()