from app.database import SessionLocal
from app.models.employee import Employee


def main():

    with SessionLocal() as session:

        employee = Employee(
            organisation_id=1,
            first_name="Ahmed",
            last_name="Khan",
            email="ahmed@example.com"
        )

        session.add(employee)
        session.commit()

        print(f"Employee created with ID: {employee.id}")


if __name__ == "__main__":
    main()