"""GST tax-invoice PDF (ReportLab). Everything printed comes from the stored invoice row,
never recomputed, so the PDF always matches the books."""
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.models import CompanyProfile, Invoice, State, Unit
from app.models.enums import SupplyType
from app.reports.amount_words import rupees_in_words

NAVY = colors.HexColor("#1B2A41")
GRID = colors.HexColor("#C9CED6")


def _inr(v: Decimal) -> str:
    """Indian digit grouping: 1234567.5 -> 12,34,567.50"""
    s = f"{Decimal(v):.2f}"
    whole, frac = s.split(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return ("-" if neg else "") + whole + "." + frac


def _qty(v: Decimal) -> str:
    return f"{Decimal(v).normalize():f}"


def render_invoice_pdf(db: Session, invoice: Invoice) -> bytes:
    company = db.get(CompanyProfile, 1)
    pos = db.get(State, invoice.place_of_supply_state_code)
    units = {u.id: u.code for u in db.query(Unit).all()}
    intra = invoice.supply_type == SupplyType.INTRA_STATE

    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, leading=11)
    title = ParagraphStyle("title", parent=styles["Title"], fontSize=15, textColor=NAVY, spaceAfter=2)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"Tax Invoice {invoice.invoice_no}", author=company.legal_name)
    story = [
        Paragraph("TAX INVOICE", title),
        Paragraph(f"<b>{company.legal_name}</b><br/>{company.address}<br/>GSTIN: <b>{company.gstin}</b>", small),
        Spacer(1, 4 * mm),
    ]
    header = Table([
        [Paragraph(f"<b>Bill to</b><br/>{invoice.customer_name}<br/>{invoice.billing_address}<br/>"
                   f"GSTIN: {invoice.customer_gstin or 'Unregistered'}", small),
         Paragraph(f"<b>Invoice No:</b> {invoice.invoice_no}<br/><b>Date:</b> {invoice.invoice_date:%d-%m-%Y}<br/>"
                   f"<b>Place of supply:</b> {pos.name} ({pos.code})<br/>"
                   f"<b>Supply:</b> {'Intra-state (CGST + SGST)' if intra else 'Inter-state (IGST)'}", small)],
    ], colWidths=[95 * mm, 87 * mm])
    header.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.6, GRID),
                                ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [header, Spacer(1, 4 * mm)]

    tax_cols = ["CGST", "SGST"] if intra else ["IGST"]
    rows = [["#", "Description", "HSN", "Qty", "Rate", "Taxable", *tax_cols, "Total"]]
    for n, it in enumerate(invoice.items, start=1):
        taxes = ([f"{_qty(it.cgst_rate)}%\n{_inr(it.cgst_amount)}", f"{_qty(it.sgst_rate)}%\n{_inr(it.sgst_amount)}"]
                 if intra else [f"{_qty(it.igst_rate)}%\n{_inr(it.igst_amount)}"])
        rows.append([str(n), it.description, it.hsn_code, f"{_qty(it.quantity)} {units[it.unit_id]}",
                     _inr(it.unit_price), _inr(it.taxable_amount), *taxes, _inr(it.line_total)])
    tax_totals = [_inr(invoice.cgst_amount), _inr(invoice.sgst_amount)] if intra else [_inr(invoice.igst_amount)]
    rows.append(["", "Total", "", "", "", _inr(invoice.taxable_amount), *tax_totals, _inr(invoice.total_amount)])
    # Must add up to the printable width: A4 210 mm - 2 x 14 mm margins = 182 mm.
    widths = [8, 36, 18, 18, 16, 22] + ([20, 20] if intra else [40]) + [24]
    table = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story += [table, Spacer(1, 3 * mm),
              Paragraph(f"<b>Invoice total: Rs {_inr(invoice.total_amount)}</b>", styles["Normal"]),
              Paragraph(rupees_in_words(invoice.total_amount), small), Spacer(1, 8 * mm),
              Paragraph(f"For <b>{company.legal_name}</b><br/><br/>Authorised Signatory", small)]
    if invoice.status.value != "ISSUED":
        story.insert(1, Paragraph(f"<font color='#B4532A'><b>{invoice.status.value.replace('_', ' ')}</b> "
                                  "(see credit notes)</font>", small))
    doc.build(story)
    return buf.getvalue()
