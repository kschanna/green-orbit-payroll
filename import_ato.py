from datetime import date

from sqlalchemy import delete

from app.database import SessionLocal
from app.models.payg_tax_table import PAYGTaxTable
from parse_ato import extract_tax_rows


EFFECTIVE_FROM = date(2026, 7, 1)


def main():
    with SessionLocal() as session:

        for frequency in ("weekly", "fortnightly", "monthly"):

            rows = extract_tax_rows(
                f"data/ato/{frequency}_2026.pdf"
            )

            # Replace existing entries for this table version
            session.execute(
                delete(PAYGTaxTable).where(
                    PAYGTaxTable.pay_frequency == frequency,
                    PAYGTaxTable.effective_from == EFFECTIVE_FROM
                )
            )

            records = []

            for earnings, with_threshold, without_threshold in rows:

                for claims_threshold, amount in (
                    (True, with_threshold),
                    (False, without_threshold),
                ):
                    records.append(
                        PAYGTaxTable(
                            pay_frequency=frequency,
                            claims_tax_free_threshold=claims_threshold,
                            gross_pay=earnings,
                            withholding_amount=amount,
                            effective_from=EFFECTIVE_FROM,
                            effective_to=None,
                        )
                    )

            session.add_all(records)

            print(
                f"{frequency.upper()}: "
                f"{len(records)} withholding entries prepared"
            )

        session.commit()

    print("ATO tax tables imported successfully!")


if __name__ == "__main__":
    main()