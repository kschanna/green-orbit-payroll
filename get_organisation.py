from sqlalchemy import select

from app.database import SessionLocal
from app.models.organisation import Organisation


def main():

    with SessionLocal() as session:

        statement = select(Organisation).where(
            Organisation.id == 1
        )

        organisation = session.scalar(statement)

        if organisation:
            print(f"ID: {organisation.id}")
            print(f"Name: {organisation.name}")
            print(f"ABN: {organisation.abn}")
            print(f"Country: {organisation.country}")
        else:
            print("Organisation not found")


if __name__ == "__main__":
    main()