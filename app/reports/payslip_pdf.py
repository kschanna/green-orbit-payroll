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

    def generate(self, payslip, employee, organisation, pay_run):

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