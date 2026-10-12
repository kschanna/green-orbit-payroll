from app.database import SessionLocal
from app.models.pay_run import PayRun
from app.payroll.pay_run_lifecycle import PayRunLifecycle


def main():
    with SessionLocal() as session:

        pay_run = session.get(PayRun, 1)

        if pay_run is None:
            raise ValueError("Pay run not found")

        print(f"Current status: {pay_run.status}")

        PayRunLifecycle().transition(
            pay_run=pay_run,
            new_status="completed"
        )

        session.commit()

        print(f"New status: {pay_run.status}")
        print(f"Pay Run #{pay_run.id} completed successfully!")


if __name__ == "__main__":
    main()