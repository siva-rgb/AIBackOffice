"""
Generate professional invoice PDFs using ReportLab.
Matches the existing pdf_generator.py patterns.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

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

from .. import store
from . import agent_logger

BRAND = colors.HexColor("#2f6fed")
INK = colors.HexColor("#14171f")
MUTED = colors.HexColor("#73798a")
GREEN = colors.HexColor("#22894f")
RED = colors.HexColor("#c72e2e")

STATUS_COLORS = {
    "draft": MUTED,
    "sent": BRAND,
    "viewed": colors.HexColor("#8b5cf6"),
    "paid": GREEN,
    "overdue": RED,
    "cancelled": MUTED,
}

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "CAD": "CA$", "AUD": "A$"}


def _sym(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(currency, currency + " ")


def generate_invoice_pdf(user_id: str, invoice_id: str) -> str:
    """Generate a PDF for an invoice. Uploads to GCS (if configured) or returns
    an in-memory path marker. Returns the GCS/storage path."""
    from ..services.storage import invoice_path, upload_pdf, is_configured

    start = datetime.now(timezone.utc)

    inv = store.get_invoice(user_id, invoice_id)
    if not inv:
        raise ValueError(f"Invoice not found: {invoice_id}")

    user = store.get_user(user_id)
    profile_raw = {}
    if user:
        p = user.profile
        profile_raw = p.model_dump() if hasattr(p, "model_dump") else (p or {})

    pdf_bytes = _render(inv, user, profile_raw)
    gcs_path = invoice_path(user_id, invoice_id)

    if is_configured():
        upload_pdf(user_id, gcs_path, pdf_bytes)

    store.update_invoice_pdf(user_id, invoice_id, gcs_path)

    latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    try:
        agent_logger.log_action(
            user_id=user_id,
            agent_type="invoice_follow_up",
            action=f"Generated PDF for invoice #{inv.invoice_number}",
            input={"invoice_id": invoice_id},
            output={"gcs_path": gcs_path, "size_bytes": len(pdf_bytes)},
            latency_ms=latency_ms,
            triggered_by="user",
        )
    except Exception:
        pass

    return gcs_path


def get_invoice_pdf_bytes(user_id: str, invoice_id: str) -> bytes:
    """Return the raw PDF bytes for streaming (used when GCS is not configured)."""
    inv = store.get_invoice(user_id, invoice_id)
    if not inv:
        raise ValueError(f"Invoice not found: {invoice_id}")
    user = store.get_user(user_id)
    profile_raw = {}
    if user:
        p = user.profile
        profile_raw = p.model_dump() if hasattr(p, "model_dump") else (p or {})
    return _render(inv, user, profile_raw)


def _render(inv, user, profile: dict) -> bytes:
    """Render invoice to PDF bytes using ReportLab."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Invoice {inv.invoice_number}",
    )

    styles = getSampleStyleSheet()
    h_title = ParagraphStyle("h_title", parent=styles["Title"], textColor=INK, fontSize=24, spaceAfter=2)
    h_label = ParagraphStyle("h_label", parent=styles["Normal"], textColor=MUTED, fontSize=8,
                              spaceAfter=0, leading=10)
    h_value = ParagraphStyle("h_value", parent=styles["Normal"], textColor=INK, fontSize=11,
                              spaceAfter=2, leading=13)
    h_brand = ParagraphStyle("h_brand", parent=styles["Heading1"], textColor=BRAND, fontSize=16,
                               spaceAfter=2)
    normal = ParagraphStyle("normal", parent=styles["Normal"], textColor=INK, fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=styles["Normal"], textColor=MUTED, fontSize=9, leading=12)
    footer_style = ParagraphStyle("footer_s", parent=styles["Normal"], textColor=MUTED,
                                   fontSize=8, leading=11)

    currency = inv.currency or "USD"
    sym = _sym(currency)
    status = (inv.status if hasattr(inv, "status") else "draft") or "draft"
    if hasattr(status, "value"):
        status = status.value

    sender_name = profile.get("business_name") or (user.business_name if user else "") or ""
    sender_address = (
        profile.get("business_address")
        or profile.get("address")
        or ""
    )
    sender_email = user.email if user else ""
    sender_tax_id = profile.get("tax_id") or ""
    invoice_footer = profile.get("invoice_footer") or ""

    line_items_raw = inv.line_items or []

    def _parse_items(items):
        result = []
        for it in items:
            if hasattr(it, "description"):
                result.append({
                    "description": it.description,
                    "qty": it.quantity,
                    "rate": it.rate,
                    "amount": it.amount or round(it.quantity * it.rate, 2),
                })
            elif isinstance(it, dict):
                qty = it.get("qty") or it.get("quantity", 1)
                rate = it.get("rate") or it.get("unit_price", 0)
                result.append({
                    "description": it.get("description", ""),
                    "qty": qty,
                    "rate": rate,
                    "amount": it.get("amount") or round(float(qty) * float(rate), 2),
                })
            elif isinstance(it, str):
                try:
                    parsed = json.loads(it)
                    result.extend(_parse_items([parsed]))
                except Exception:
                    pass
        return result

    items = _parse_items(line_items_raw)

    status_color = STATUS_COLORS.get(status, MUTED)

    story = []

    # ── Header row: sender left, invoice info right ──────────────────────────
    sender_lines = [Paragraph(f"<b>{sender_name}</b>", h_brand)] if sender_name else []
    if sender_address:
        for line in sender_address.replace("\r\n", "\n").split("\n"):
            if line.strip():
                sender_lines.append(Paragraph(line.strip(), small))
    if sender_email:
        sender_lines.append(Paragraph(sender_email, small))
    if sender_tax_id:
        sender_lines.append(Paragraph(f"Tax ID: {sender_tax_id}", small))

    invoice_date_str = inv.invoice_date or (inv.created_at[:10] if inv.created_at else "")
    invoice_meta = [
        [Paragraph("INVOICE", h_title)],
        [Paragraph(f"#{inv.invoice_number}", ParagraphStyle("inv_num", parent=styles["Normal"],
                                                             textColor=MUTED, fontSize=12))],
        [Paragraph(f'<font color="#{_hex(status_color)}">{status.upper()}</font>',
                   ParagraphStyle("status", parent=styles["Normal"], fontSize=10, leading=14))],
    ]

    header_data = [[
        sender_lines or [Paragraph("", normal)],
        [t[0] for t in invoice_meta],
    ]]
    # Render header as two-column table
    from reportlab.platypus import KeepTogether
    left_col = []
    for p in (sender_lines or [Paragraph("", normal)]):
        left_col.append(p)
    right_col = [Paragraph("INVOICE", h_title),
                 Paragraph(f"#{inv.invoice_number}", ParagraphStyle("inv_num", parent=styles["Normal"],
                                                                      textColor=MUTED, fontSize=12)),
                 Paragraph(f'<font color="#{_hex(status_color)}">{status.upper()}</font>',
                            ParagraphStyle("status", parent=styles["Normal"], fontSize=10, leading=14))]

    header_table = Table(
        [[left_col, right_col]],
        colWidths=[105 * mm, 60 * mm],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10 * mm))

    # ── Parties row ──────────────────────────────────────────────────────────
    client_lines = [
        Paragraph("BILL TO", h_label),
        Paragraph(inv.client_name or "", h_value),
    ]
    if inv.client_address:
        for line in inv.client_address.replace("\r\n", "\n").split("\n"):
            if line.strip():
                client_lines.append(Paragraph(line.strip(), small))
    if inv.client_email:
        client_lines.append(Paragraph(inv.client_email, small))
    if inv.client_tax_id:
        client_lines.append(Paragraph(f"Tax ID: {inv.client_tax_id}", small))

    date_lines = [
        Paragraph("INVOICE DATE", h_label),
        Paragraph(invoice_date_str or "—", h_value),
        Spacer(1, 4 * mm),
        Paragraph("DUE DATE", h_label),
        Paragraph(inv.due_date or "—", h_value),
    ]
    if inv.payment_terms:
        date_lines += [
            Spacer(1, 4 * mm),
            Paragraph("PAYMENT TERMS", h_label),
            Paragraph(inv.payment_terms, h_value),
        ]
    if inv.po_number:
        date_lines += [
            Spacer(1, 4 * mm),
            Paragraph("PO / REFERENCE", h_label),
            Paragraph(inv.po_number, h_value),
        ]

    parties_table = Table(
        [[client_lines, date_lines]],
        colWidths=[105 * mm, 60 * mm],
    )
    parties_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(parties_table)
    story.append(Spacer(1, 8 * mm))

    # ── Line items table ─────────────────────────────────────────────────────
    col_w = [10 * mm, 85 * mm, 20 * mm, 25 * mm, 25 * mm]
    header_row = [
        Paragraph("#", ParagraphStyle("th", parent=styles["Normal"], textColor=colors.white,
                                       fontSize=9, fontName="Helvetica-Bold")),
        Paragraph("Description", ParagraphStyle("th", parent=styles["Normal"], textColor=colors.white,
                                                  fontSize=9, fontName="Helvetica-Bold")),
        Paragraph("Qty", ParagraphStyle("th", parent=styles["Normal"], textColor=colors.white,
                                         fontSize=9, fontName="Helvetica-Bold", alignment=1)),
        Paragraph("Rate", ParagraphStyle("th", parent=styles["Normal"], textColor=colors.white,
                                          fontSize=9, fontName="Helvetica-Bold", alignment=2)),
        Paragraph("Amount", ParagraphStyle("th", parent=styles["Normal"], textColor=colors.white,
                                            fontSize=9, fontName="Helvetica-Bold", alignment=2)),
    ]
    rows = [header_row]
    for i, it in enumerate(items, 1):
        rows.append([
            Paragraph(str(i), normal),
            Paragraph(str(it["description"]), normal),
            Paragraph(str(it["qty"]), ParagraphStyle("center", parent=styles["Normal"],
                                                      fontSize=10, alignment=1)),
            Paragraph(f'{sym}{float(it["rate"]):,.2f}', ParagraphStyle("right", parent=styles["Normal"],
                                                                         fontSize=10, alignment=2)),
            Paragraph(f'{sym}{float(it["amount"]):,.2f}', ParagraphStyle("right", parent=styles["Normal"],
                                                                           fontSize=10, alignment=2)),
        ])

    items_table = Table(rows, colWidths=col_w)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 6 * mm))

    # ── Totals ───────────────────────────────────────────────────────────────
    totals_data = [
        [Paragraph("Subtotal", normal), Paragraph(f"{sym}{inv.subtotal:,.2f}",
                                                    ParagraphStyle("r", parent=styles["Normal"],
                                                                    fontSize=10, alignment=2))],
    ]
    if inv.tax_rate:
        totals_data.append([
            Paragraph(f"Tax ({inv.tax_rate}%)", normal),
            Paragraph(f"{sym}{inv.tax_amount:,.2f}",
                      ParagraphStyle("r", parent=styles["Normal"], fontSize=10, alignment=2)),
        ])
    totals_data.append([
        Paragraph("<b>Total</b>", ParagraphStyle("tot_l", parent=styles["Normal"],
                                                  fontSize=13, fontName="Helvetica-Bold")),
        Paragraph(f"<b>{sym}{inv.total:,.2f}</b>",
                  ParagraphStyle("tot_r", parent=styles["Normal"], fontSize=13,
                                  fontName="Helvetica-Bold", alignment=2)),
    ])

    totals_table = Table(totals_data, colWidths=[130 * mm, 35 * mm],
                         hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals_table)

    # ── Footer ───────────────────────────────────────────────────────────────
    story.append(Spacer(1, 10 * mm))
    if invoice_footer:
        story.append(Paragraph(invoice_footer.replace("\n", "<br/>"), footer_style))
        story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Generated by Kora (kora.app)", footer_style))

    doc.build(story)
    return buf.getvalue()


def _hex(color) -> str:
    """Convert ReportLab Color to hex string without '#'."""
    r = int(color.red * 255)
    g = int(color.green * 255)
    b = int(color.blue * 255)
    return f"{r:02x}{g:02x}{b:02x}"
