from app.database import SessionLocal
from app.models.organisation import Organisation


def main():

    with SessionLocal() as session:

        organisation = Organisation(
            name="Green Orbit Demo Pty Ltd",
            abn="00000000000",
            country="AU"
        )

        session.add(organisation)

        session.commit()

        print(f"Organisation created with ID: {organisation.id}")


if __name__ == "__main__":
    main()