from app.utils.dates import format_date_au
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


class PayslipPDFGenerator:

    def generate(
        self,
        payslip,
        employee,
        organisation,
        pay_run,
        earnings_lines=None,
        withholding_lines=None,
        employer_super_lines=None,
    ):

        buffer = BytesIO()

        document = SimpleDocTemplate(
            buffer,
            pagesize=A4
        )

        styles = getSampleStyleSheet()
        elements = []

        # Heading
        elements.append(
            Paragraph("GREEN ORBIT — PAYSLIP", styles["Title"])
        )

        elements.append(Spacer(1, 20))

        # Employer and employee details
        elements.append(
            Paragraph(
                f"<b>Employer:</b> {organisation.name}",
                styles["Normal"]
            )
        )

        elements.append(
            Paragraph(
                f"<b>Employee:</b> "
                f"{employee.first_name} {employee.last_name}",
                styles["Normal"]
            )
        )

        elements.append(
            Paragraph(
                f"<b>Pay period:</b> "
                f"{format_date_au(pay_run.period_start)} to {format_date_au(pay_run.period_end)}",
                styles["Normal"]
            )
        )

        elements.append(
            Paragraph(
                f"<b>Payment date:</b> {format_date_au(pay_run.payment_date)}",
                styles["Normal"]
            )
        )

        elements.append(Spacer(1, 25))

        # Assignment and payroll component breakdown
        if earnings_lines:
            elements.append(
                Paragraph("Earnings Breakdown", styles["Heading2"])
            )

            elements.append(Spacer(1, 10))

            earnings_data = [[
                "Assignment",
                "Payroll Component",
                "Hours / Qty",
                "Rate",
                "Amount"
            ]]

            for line in earnings_lines:
                earnings_data.append([
                    str(line["assignment"]),
                    Paragraph(
                        str(line["component"]),
                        styles["Normal"]
                    ),
                    (
                        f'{line["quantity"]:,.2f}'
                        if line["quantity"] is not None
                        else "—"
                    ),
                    (
                        f'${line["rate"]:,.2f}'
                        if line["rate"] is not None
                        else "—"
                    ),
                    f'${line["amount"]:,.2f}'
                ])

            earnings_table = Table(
                earnings_data,
                colWidths=[75, 145, 75, 75, 80],
                repeatRows=1
            )

            earnings_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ])
            )

            elements.append(earnings_table)
            elements.append(Spacer(1, 20))

        # Realised employee withholding and employer contributions.
        for heading, lines in (
            ("Employee Withholding", withholding_lines),
            ("Employer Superannuation", employer_super_lines),
        ):
            if not lines:
                continue

            elements.append(
                Paragraph(heading, styles["Heading2"])
            )
            elements.append(Spacer(1, 10))

            section_data = [["Component", "Amount"]]

            for line in lines:
                section_data.append([
                    Paragraph(
                        str(line["component"]),
                        styles["Normal"]
                    ),
                    f'${line["amount"]:,.2f}',
                ])

            section_table = Table(
                section_data,
                colWidths=[300, 150],
                repeatRows=1
            )

            section_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ])
            )

            elements.append(section_table)
            elements.append(Spacer(1, 20))

        # Payroll amounts
        data = [
            ["Description", "Amount"],
            ["Gross Pay", f"${payslip.gross_pay:,.2f}"],
            ["PAYG Withholding", f"${payslip.payg_withholding:,.2f}"],
            ["Net Pay", f"${payslip.net_pay:,.2f}"],
            ["Employer Superannuation", f"${payslip.superannuation:,.2f}"],
        ]

        table = Table(data, colWidths=[300, 150])

        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
            ])
        )

        elements.append(table)

        elements.append(Spacer(1, 30))

        elements.append(
            Paragraph(
                "Demonstration payslip — not for production payroll use.",
                styles["Italic"]
            )
        )

        document.build(elements)

        buffer.seek(0)

        return buffer