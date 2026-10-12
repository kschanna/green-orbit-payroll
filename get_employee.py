from sqlalchemy import select

from app.database import SessionLocal
from app.models.employee import Employee


def main():

    with SessionLocal() as session:

        statement = select(Employee).where(Employee.id == 1)

        employee = session.scalar(statement)

        if employee:

            print(f"Employee ID: {employee.id}")
            print(f"Name: {employee.first_name} {employee.last_name}")
            print(f"Email: {employee.email}")

            print(f"Organisation: {employee.organisation.name}")

        else:
            print("Employee not found")


if __name__ == "__main__":
    main()