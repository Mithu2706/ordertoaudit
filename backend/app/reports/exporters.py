"""Render a Report as CSV, Excel (openpyxl) or PDF (ReportLab). Values are written exactly:
Decimals go to Excel as numbers from their exact text (no float maths in our code)."""
import csv
from datetime import date, datetime
from xml.sax.saxutils import escape
from decimal import Decimal
from io import BytesIO, StringIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.reports.framework import NUMERIC, Kind, Report

NAVY = "1B2A41"
EXCEL_FORMATS = {Kind.MONEY: "#,##0.00", Kind.QTY: "#,##0.####", Kind.RATE: "#,##0.000000",
                 Kind.PCT: "0.00", Kind.INT: "0", Kind.DATE: "dd-mm-yyyy"}


def _text(value: Any, kind: Kind) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        if kind == Kind.MONEY:
            return f"{value:,.2f}"
        if kind == Kind.PCT:
            return f"{value:.2f}"
        if kind == Kind.RATE:
            return f"{value:.6f}"
        return f"{value.normalize():f}"  # quantities / counts: 238, 19.5, 1.2
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    return str(value)


def _filter_line(rep: Report) -> str:
    return " | ".join(f"{k}: {v}" for k, v in rep.filters.items())


# ---- CSV ------------------------------------------------------------------------------
def to_csv(rep: Report) -> bytes:
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow([c.label for c in rep.columns])
    for r in rep.rows:
        w.writerow(["" if r.get(c.key) is None else
                    (f"{r[c.key]:f}" if isinstance(r[c.key], Decimal) else
                     r[c.key].isoformat() if isinstance(r[c.key], date) else
                     ("Yes" if r[c.key] else "No") if isinstance(r[c.key], bool) else r[c.key])
                    for c in rep.columns])
    totals = rep.totals
    if totals:
        w.writerow(["TOTAL" if i == 0 else (f"{totals[c.key]:f}" if c.key in totals else "")
                    for i, c in enumerate(rep.columns)])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel opens UTF-8 (₹) correctly


# ---- Excel ----------------------------------------------------------------------------
def to_xlsx(rep: Report) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = rep.key[:31]
    ws.append([rep.title])
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws.append([_filter_line(rep)])
    ws.append([])
    header_row = 4
    ws.append([c.label for c in rep.columns])
    for i, _ in enumerate(rep.columns, start=1):
        cell = ws.cell(row=header_row, column=i)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for r in rep.rows:
        ws.append([r.get(c.key) for c in rep.columns])
    totals = rep.totals
    if totals:
        ws.append(["TOTAL" if i == 0 else totals.get(c.key) for i, c in enumerate(rep.columns)])
        for i in range(1, len(rep.columns) + 1):
            ws.cell(row=ws.max_row, column=i).font = Font(bold=True)
    for i, c in enumerate(rep.columns, start=1):
        fmt = EXCEL_FORMATS.get(c.kind)
        if fmt:
            for row in range(header_row + 1, ws.max_row + 1):
                ws.cell(row=row, column=i).number_format = fmt
        width = max([len(c.label)] + [len(_text(r.get(c.key), c.kind)) for r in rep.rows]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(max(width, 9), 45)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    for note in rep.notes:
        ws.append([])
        ws.append([note])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- PDF ------------------------------------------------------------------------------
def to_pdf(rep: Report, company_name: str = "") -> bytes:
    styles = getSampleStyleSheet()
    buf = BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title=rep.title)
    small = styles["Normal"].clone("small", fontSize=8, leading=10)
    story = [Paragraph(f"<b>{rep.title}</b>", styles["Title"]),
             Paragraph(f"{company_name} &nbsp;|&nbsp; {_filter_line(rep)} &nbsp;|&nbsp; "
                       f"generated {datetime.now():%d-%m-%Y %H:%M}", small), Spacer(1, 4 * mm)]
    # Paragraph cells ignore the table's TEXTCOLOR, so the header style itself must be white;
    # text cells are Paragraphs too, so long names wrap instead of spilling into the next cell.
    head = small.clone("head", textColor=colors.white, fontName="Helvetica-Bold")
    cell = small.clone("cell", fontSize=7.5, leading=9)
    data = [[Paragraph(c.label, head) for c in rep.columns]]
    for r in rep.rows:
        data.append([Paragraph(escape(_text(r.get(c.key), c.kind)), cell) if c.kind == Kind.TEXT
                     else _text(r.get(c.key), c.kind) for c in rep.columns])
    totals = rep.totals
    if totals:
        data.append(["TOTAL" if i == 0 else _text(totals.get(c.key), c.kind) for i, c in enumerate(rep.columns)])
    if not rep.rows:
        data.append(["No records for the selected period"] + [""] * (len(rep.columns) - 1))

    usable = page[0] - 20 * mm
    # Size each column by its longest value (capped), so codes like PRD/2026-27/00001 don't break.
    weights = [min(max([len(c.label), 7] + [len(_text(r.get(c.key), c.kind)) for r in rep.rows]), 28) + 2
               for c in rep.columns]
    widths = [usable * w / sum(weights) for w in weights]
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9CED6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F6F8")]),
    ]
    for i, c in enumerate(rep.columns):
        if c.kind in NUMERIC:
            style.append(("ALIGN", (i, 1), (i, -1), "RIGHT"))
    if totals:
        style.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))
    story.append(table)
    for note in rep.notes:
        story += [Spacer(1, 2 * mm), Paragraph(note, small)]
    doc.build(story)
    return buf.getvalue()
