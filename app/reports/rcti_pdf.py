from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.utils.dates import format_date_au


class RCTIPDFGenerator:
    def generate(
        self, *, payslip, pay_run, recipient, supplier, contractor_name,
        supply_lines, deduction_lines, gst_paid, source_reference=None,
    ):
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name="RCTITitle", parent=styles["Title"], fontName="Helvetica-Bold",
            fontSize=17, leading=21, alignment=TA_CENTER, spaceAfter=4,
        ))
        styles.add(ParagraphStyle(
            name="SmallRight", parent=styles["Normal"], fontSize=8,
            leading=10, alignment=TA_RIGHT,
        ))
        styles.add(ParagraphStyle(
            name="Small", parent=styles["Normal"], fontSize=8, leading=10,
        ))

        title = "RECIPIENT CREATED TAX INVOICE"
        if pay_run.status == "draft":
            title += "<br/><font color='#a00000' size='11'>DRAFT</font>"
        elements = [Paragraph(title, styles["RCTITitle"])]
        elements.extend([
            Paragraph(f"RCTI #{payslip.id}", styles["SmallRight"]),
            Paragraph(
                f"Date: {format_date_au(pay_run.payment_date)} &nbsp;&nbsp; "
                f"Pay Run: #{pay_run.id}", styles["SmallRight"]
            ),
        ])
        if source_reference:
            elements.append(Paragraph(
                f"Source: {source_reference}", styles["SmallRight"]
            ))
        elements.append(Spacer(1, 7 * mm))

        party_data = [
            [Paragraph("<b>FROM - RECIPIENT</b>", styles["Normal"]),
             Paragraph("<b>TO - SUPPLIER</b>", styles["Normal"])],
            [Paragraph(
                f"<b>{recipient.name}</b><br/>ABN: {recipient.abn}<br/>"
                f"Country: {recipient.country}", styles["Normal"]
             ), Paragraph(
                f"<b>{supplier.name}</b><br/>ABN: {supplier.abn}<br/>"
                f"Country: {supplier.country}<br/>Contractor: {contractor_name}",
                styles["Normal"]
             )],
        ]
        party_table = Table(party_data, colWidths=[87 * mm, 87 * mm])
        party_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#333333")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#777777")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ]))
        elements.extend([party_table, Spacer(1, 7 * mm)])

        elements.append(Paragraph(
            "<b>SUPPLIES MADE BY SUPPLIER TO RECIPIENT</b>", styles["Heading3"]
        ))
        rows = [["Description of taxable supplies", "Value", "GST", "Price"]]
        for line in supply_lines:
            rows.append([
                Paragraph(line["name"], styles["Small"]),
                f'${line["amount"]:,.2f}', "-", f'${line["amount"]:,.2f}',
            ])
        for line in deduction_lines:
            rows.append([
                Paragraph(line["name"], styles["Small"]),
                f'-${line["amount"]:,.2f}', "-", f'-${line["amount"]:,.2f}',
            ])
        taxable_value = payslip.net_pay - gst_paid
        rows.extend([
            ["TOTALS", f"${taxable_value:,.2f}", f"${gst_paid:,.2f}",
             f"${payslip.net_pay:,.2f}"],
            ["AMOUNT DEPOSITED TO YOUR BANK ACCOUNT", "", "",
             f"${payslip.net_pay:,.2f}"],
        ])
        supplies = Table(
            rows, colWidths=[91 * mm, 28 * mm, 25 * mm, 30 * mm], repeatRows=1
        )
        supplies.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#555555")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eeeeee")),
            ("SPAN", (0, -1), (2, -1)),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.extend([supplies, Spacer(1, 5 * mm)])

        agreement = KeepTogether([
            Paragraph(
                "The GST shown forms part of the supplier's GST payable for the "
                "relevant tax period.", styles["Small"]
            ),
            Spacer(1, 3 * mm),
            Paragraph("<b>Written Agreement</b>", styles["Normal"]),
            Paragraph(
                "The recipient may issue tax invoices for these supplies and the "
                "supplier will not issue a separate tax invoice. Both parties confirm "
                "they are registered for GST and will notify the other party if that "
                "changes. Accepting this RCTI confirms agreement to these terms. The "
                "supplier should notify the recipient within 21 days if it does not "
                "accept the proposed agreement.", styles["Small"]
            ),
        ])
        elements.append(agreement)

        document.build(elements)
        buffer.seek(0)
        return buffer
