from app.database import SessionLocal
from app.payroll.pay_run_processor import PayRunProcessor


def main():

    with SessionLocal() as session:

        processor = PayRunProcessor()

        result = processor.process(
            session=session,
            pay_run_id=1
        )

        print("Payroll processing complete!")
        print(f"Employees processed: {result['processed']}")
        print(f"Employees skipped: {result['skipped']}")


if __name__ == "__main__":
    main()