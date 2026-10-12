import re
import pdfplumber

from pathlib import Path
from decimal import Decimal


def extract_tax_rows(pdf_path):
    rows = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()

            if not text:
                continue

            for line in text.splitlines():
                values = line.split()

                # Four groups of three columns
                if len(values) != 12:
                    continue

                # Accept only numeric data
                if not all(
                    re.fullmatch(r"[\d,]+(?:\.\d+)?", value)
                    for value in values
                ):
                    continue

                # Skip repeated column headings
                if values == ["1", "2", "3"] * 4:
                    continue

                for i in range(0, 12, 3):
                    earnings = Decimal(values[i].replace(",", ""))
                    with_threshold = Decimal(values[i + 1].replace(",", ""))
                    without_threshold = Decimal(values[i + 2].replace(",", ""))

                    rows.append((
                        earnings,
                        with_threshold,
                        without_threshold
                    ))

    # Sort by earnings
    rows.sort(key=lambda row: row[0])

    # Check for duplicate earnings
    earnings = [row[0] for row in rows]

    if len(earnings) != len(set(earnings)):
        raise ValueError(f"Duplicate earnings found in {pdf_path}")

    return rows


if __name__ == "__main__":

    for frequency in ("weekly", "fortnightly", "monthly"):

        path = Path(f"data/ato/{frequency}_2026.pdf")

        rows = extract_tax_rows(path)

        print(f"\n{frequency.upper()}: {len(rows)} rows")

        print("First 5:")
        for row in rows[:5]:
            print(row)

        print("Last 5:")
        for row in rows[-5:]:
            print(row)