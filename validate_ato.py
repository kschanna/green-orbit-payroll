from decimal import Decimal

from parse_ato import extract_tax_rows


expected = {
    "weekly": (3400, Decimal("1"), Decimal("3400")),
    "fortnightly": (3400, Decimal("2"), Decimal("6800")),
    "monthly": (2880, Decimal("4.33"), Decimal("12480")),
}

for frequency, (count, minimum, maximum) in expected.items():

    rows = extract_tax_rows(f"data/ato/{frequency}_2026.pdf")

    assert len(rows) == count
    assert rows[0][0] == minimum
    assert rows[-1][0] == maximum

    earnings = [row[0] for row in rows]

    assert earnings == sorted(earnings)
    assert len(earnings) == len(set(earnings))

    if frequency == "weekly":
        assert earnings == [
            Decimal(i) for i in range(1, 3401)
        ]

    elif frequency == "fortnightly":
        assert earnings == [
            Decimal(i * 2) for i in range(1, 3401)
        ]

    print(f"{frequency.upper()}: PASSED")