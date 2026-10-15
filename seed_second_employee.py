from datetime import date
from decimal import Decimal

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.work_pattern import WorkPattern


def main():

    with SessionLocal() as session:

        # Check whether Sarah already exists
        employee = (
            session.query(Employee)
            .filter_by(email="sarah@example.com")
            .first()
        )

        if employee is not None:
            print(f"Sarah already exists. Employee ID: {employee.id}")
            return

        # Create Sarah
        employee = Employee(
            organisation_id=1,
            first_name="Sarah",
            last_name="Mitchell",
            email="sarah@example.com"
        )

        session.add(employee)
        session.flush()

        # Create her work pattern
        agreement = WorkPattern(
            employee_id=employee.id,
            employment_type="full_time",
            pay_basis="hourly",
            hourly_rate=Decimal("55.00"),
            ordinary_hours_per_week=Decimal("38.00"),
            pay_frequency="fortnightly",
            start_date=date(2026, 10, 1),
            end_date=None
        )

        session.add(agreement)
        session.commit()

        print(f"Employee created: {employee.id}")
        print(f"Name: {employee.first_name} {employee.last_name}")
        print(f"Hourly rate: ${agreement.hourly_rate}")
        print(f"Pay frequency: {agreement.pay_frequency}")


if __name__ == "__main__":
    main()