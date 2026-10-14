from io import BytesIO
from xml.sax.saxutils import escape

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


class InvoicePDFGenerator:

    def generate(self, invoice, engagement, employee, supplier, customer, hours):

        buffer = BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4)

        styles = getSampleStyleSheet()
        elements = []

        # Heading
        elements.append(
            Paragraph("TAX INVOICE", styles["Title"])
        )

        elements.append(Spacer(1, 20))

        # Supplier and customer
        details = [
            ("Supplier", supplier.name),
            ("Supplier ABN", supplier.abn),
            ("Customer", customer.name),
            ("Invoice number", invoice.invoice_number),
            ("Invoice date", str(invoice.issue_date)),
            ("Worker", f"{employee.first_name} {employee.last_name}"),
        ]

        for label, value in details:
            elements.append(
                Paragraph(
                    f"<b>{label}:</b> {escape(str(value))}",
                    styles["Normal"]
                )
            )

        elements.append(Spacer(1, 25))

        # Invoice amounts
        data = [
            ["Description", "Amount"],
            [
                f"{hours:.2f} hours @ ${engagement.billing_rate:.2f}",
                f"${invoice.subtotal:,.2f}"
            ],
            ["GST (10%)", f"${invoice.gst:,.2f}"],
            ["TOTAL", f"${invoice.total:,.2f}"],
        ]

        table = Table(data, colWidths=[300, 150])

        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ])
        )

        elements.append(table)

        elements.append(Spacer(1, 30))

        elements.append(
            Paragraph(
                "Demonstration invoice — not for commercial use.",
                styles["Italic"]
            )
        )

        document.build(elements)
        buffer.seek(0)

        return buffer