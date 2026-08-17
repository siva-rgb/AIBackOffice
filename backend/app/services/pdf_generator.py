from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..models import User
from .pnl import PnL

# P&L report PDF using ReportLab (SKILL.md §2 — "ReportLab gives
# professional-grade PDF output"). Structure mirrors modules.md#bookkeeper.

BRAND = colors.HexColor("#2f6fed")
INK = colors.HexColor("#14171f")
MUTED = colors.HexColor("#73798a")
GREEN = colors.HexColor("#22894f")
RED = colors.HexColor("#c72e2e")


def _humanize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("_", " ").split())


def generate_pnl_pdf(user: User, pnl: PnL, period_start: str, period_end: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Kora P&L Statement",
    )
    styles = getSampleStyleSheet()
    h_brand = ParagraphStyle("brand", parent=styles["Title"], textColor=BRAND, fontSize=22, spaceAfter=2)
    h_biz = ParagraphStyle("biz", parent=styles["Heading2"], textColor=INK, fontSize=14, spaceAfter=0)
    sub = ParagraphStyle("sub", parent=styles["Normal"], textColor=MUTED, fontSize=10, spaceAfter=2)
    h_sec = ParagraphStyle("sec", parent=styles["Heading3"], textColor=INK, fontSize=12, spaceBefore=10, spaceAfter=6)

    cur = "$" if user.currency == "USD" else user.currency + " "

    def money(n: float) -> str:
        return f"{cur}{n:,.2f}"

    elems = []
    elems.append(Paragraph("Kora", h_brand))
    elems.append(Paragraph(user.business_name or user.full_name or "Your business", h_biz))
    elems.append(Paragraph("Profit &amp; Loss Statement", sub))
    elems.append(Paragraph(f"Period: {period_start} to {period_end}", sub))
    elems.append(Spacer(1, 8 * mm))

    # Summary table
    elems.append(Paragraph("Summary", h_sec))
    net_color = GREEN if pnl.net_profit >= 0 else RED
    summary_data = [
        ["Total income", money(pnl.total_income)],
        ["Total expenses", money(pnl.total_expenses)],
        ["Net profit", money(pnl.net_profit)],
        ["Profit margin", f"{pnl.profit_margin}%"],
        ["Tax-deductible expenses", money(pnl.deductible_expenses)],
    ]
    st = Table(summary_data, colWidths=[100 * mm, 59 * mm])
    st.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
                ("TEXTCOLOR", (1, 0), (1, 0), GREEN),
                ("TEXTCOLOR", (1, 1), (1, 1), RED),
                ("TEXTCOLOR", (1, 2), (1, 2), net_color),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e6e8ee")),
            ]
        )
    )
    elems.append(st)

    def category_table(title: str, data: dict[str, float]):
        elems.append(Paragraph(title, h_sec))
        if not data:
            elems.append(Paragraph("No data.", sub))
            return
        rows = [[_humanize(k), money(v)] for k, v in sorted(data.items(), key=lambda kv: kv[1], reverse=True)]
        t = Table(rows, colWidths=[100 * mm, 59 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#eef0f4")),
                ]
            )
        )
        elems.append(t)

    category_table("Income by category", pnl.income_by_category)
    category_table("Expenses by category", pnl.expense_by_category)

    # Top transactions
    elems.append(Paragraph("Top transactions", h_sec))
    top_rows = [["Date", "Description", "Amount"]]
    for t in pnl.top_transactions:
        desc = t["description"]
        if len(desc) > 48:
            desc = desc[:47] + "…"
        top_rows.append([t["date"], desc, money(t["amount"])])
    tt = Table(top_rows, colWidths=[28 * mm, 100 * mm, 31 * mm])
    tt.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f8")),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#eef0f4")),
            ]
        )
    )
    elems.append(tt)

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"Generated by Kora AI · kora.app   ·   Page {doc_.page}")
        canvas.restoreState()

    doc.build(elems, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def generate_contract_pdf(title: str, content_md: str) -> bytes:
    """Render a generated contract's Markdown into a professional PDF
    (SKILL.md modules.md#contracts) with a signature-ready footer."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=title or "Kora Contract",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=18, textColor=INK, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, textColor=INK, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=15, spaceAfter=6)
    note = ParagraphStyle("note", parent=styles["Italic"], fontSize=8.5, textColor=MUTED, spaceAfter=8)

    def esc(s: str) -> str:
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # bold **x**
        import re as _re

        return _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)

    elems = []
    for raw in (content_md or "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            elems.append(Spacer(1, 4))
            continue
        if line.startswith("# "):
            elems.append(Paragraph(esc(line[2:]), h1))
        elif line.startswith("## "):
            elems.append(Paragraph(esc(line[3:]), h2))
        elif line.startswith("### "):
            elems.append(Paragraph(esc(line[4:]), h2))
        elif line.startswith("_") and line.endswith("_"):
            elems.append(Paragraph(esc(line.strip("_")), note))
        elif line.startswith(("- ", "* ")):
            elems.append(Paragraph("• " + esc(line[2:]), body))
        else:
            elems.append(Paragraph(esc(line), body))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 12 * mm, f"Prepared with Kora AI · kora.app · Not a substitute for legal advice · Page {doc_.page}")
        canvas.restoreState()

    doc.build(elems, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
