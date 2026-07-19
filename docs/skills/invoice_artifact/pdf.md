# Invoice Enhancements — PDF Generation Reference

Use the same PDF library already in the codebase (ReportLab or WeasyPrint).
Check `services/pdf_generator.py` to see which is used for contracts/P&L.
This reference shows both approaches — use whichever matches the existing code.

---

## Invoice PDF service

```python
# backend/app/services/invoice_pdf.py
"""
Generate professional invoice PDFs.
Uses the same PDF library as the existing contract/P&L generator.
"""
from datetime import datetime
from app import store
from app.services.storage import upload_pdf, contract_path
from app.services.agent_logger import log_agent_action
from app.models import AgentType


async def generate_invoice_pdf(user_id: str, invoice_id: str) -> str:
    """
    Generate a PDF for an invoice. Store in GCS. Return the GCS path.
    The path is saved to invoices.pdf_path in the DB.
    """
    start = datetime.utcnow()

    # Fetch invoice + user profile for sender details
    invoice = store.get_invoice(user_id, invoice_id)
    if not invoice:
        raise ValueError("Invoice not found")

    user = store.get_user(user_id)
    profile = user.get("profile") or {} if user else {}

    # Build the PDF data context
    context = _build_pdf_context(invoice, user, profile)

    # Generate the PDF bytes
    pdf_bytes = _render_invoice_pdf(context)

    # Upload to GCS
    gcs_path = f"users/{user_id}/invoices/{invoice_id}.pdf"
    upload_pdf(user_id, gcs_path, pdf_bytes)

    # Save path to DB
    store.update_invoice_pdf(user_id, invoice_id, gcs_path)

    latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    try:
        log_agent_action(
            user_id=user_id,
            agent_type=AgentType.invoice_follow_up,
            action=f"Generated invoice PDF: #{invoice.get('invoice_number', invoice_id[:8])}",
            input_data={"invoice_id": invoice_id},
            output_data={"gcs_path": gcs_path, "size_bytes": len(pdf_bytes)},
            latency_ms=latency_ms,
            triggered_by="user",
        )
    except Exception:
        pass

    return gcs_path


def _build_pdf_context(invoice: dict, user: dict, profile: dict) -> dict:
    """Assemble all data needed for the PDF template."""
    line_items = invoice.get("line_items", [])
    if isinstance(line_items, str):
        import json
        line_items = json.loads(line_items)

    return {
        # Sender (the user's business)
        "sender_name": profile.get("business_name") or user.get("full_name", ""),
        "sender_address": user.get("business_address", ""),
        "sender_email": user.get("email", ""),
        "sender_tax_id": user.get("tax_id", ""),

        # Recipient (the client)
        "client_name": invoice.get("client_name", ""),
        "client_email": invoice.get("client_email", ""),
        "client_address": invoice.get("client_address", ""),
        "client_tax_id": invoice.get("client_tax_id", ""),

        # Invoice details
        "invoice_number": invoice.get("invoice_number", ""),
        "invoice_date": invoice.get("invoice_date") or
                        (invoice.get("created_at", "")[:10] if invoice.get("created_at") else ""),
        "due_date": invoice.get("due_date", ""),
        "payment_terms": invoice.get("payment_terms", ""),
        "po_number": invoice.get("po_number", ""),
        "currency": invoice.get("currency", "USD"),

        # Line items
        "line_items": line_items,
        "subtotal": invoice.get("subtotal", 0),
        "tax_rate": invoice.get("tax_rate", 0),
        "tax_amount": round(invoice.get("subtotal", 0) * invoice.get("tax_rate", 0) / 100, 2),
        "total": invoice.get("total", 0),

        # Footer
        "footer": user.get("invoice_footer", ""),
        "status": invoice.get("status", "draft"),
    }


def _render_invoice_pdf(ctx: dict) -> bytes:
    """
    Render the invoice PDF. Uses WeasyPrint (HTML→PDF) for flexibility.
    If the codebase uses ReportLab instead, adapt this to ReportLab.
    
    Check services/pdf_generator.py — use the same library.
    """
    currency = ctx["currency"]
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency, currency + " ")

    # Build line items HTML
    items_html = ""
    for i, item in enumerate(ctx["line_items"], 1):
        desc = item.get("description", "")
        qty = item.get("qty") or item.get("quantity", 1)
        rate = item.get("rate") or item.get("unit_price", 0)
        amount = item.get("amount") or round(float(qty) * float(rate), 2)
        items_html += f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">{i}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">{desc}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center;">{qty}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{symbol}{rate:,.2f}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{symbol}{amount:,.2f}</td>
        </tr>"""

    # Status badge
    status = ctx["status"].upper()
    status_color = {
        "DRAFT": "#6b7280", "SENT": "#3b82f6", "VIEWED": "#8b5cf6",
        "PAID": "#10b981", "OVERDUE": "#ef4444", "CANCELLED": "#6b7280",
    }.get(status, "#6b7280")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: A4; margin: 40px; }}
            body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1a1a1a; font-size: 13px; line-height: 1.5; }}
            .header {{ display: flex; justify-content: space-between; margin-bottom: 40px; }}
            .sender {{ max-width: 50%; }}
            .invoice-meta {{ text-align: right; }}
            .invoice-title {{ font-size: 28px; font-weight: 300; color: #111; margin: 0; }}
            .invoice-number {{ font-size: 14px; color: #666; margin: 4px 0; }}
            .status-badge {{ display: inline-block; padding: 3px 12px; border-radius: 12px;
                            color: white; font-size: 11px; font-weight: 500;
                            background: {status_color}; }}
            .parties {{ display: flex; justify-content: space-between; margin: 30px 0; }}
            .party {{ max-width: 45%; }}
            .party-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 1px;
                           color: #999; margin-bottom: 4px; }}
            .party-name {{ font-size: 15px; font-weight: 500; }}
            .party-detail {{ font-size: 12px; color: #666; white-space: pre-line; }}
            table {{ width: 100%; border-collapse: collapse; margin: 30px 0; }}
            th {{ background: #f8f9fa; padding: 10px 12px; text-align: left;
                 font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
                 color: #666; border-bottom: 2px solid #e5e7eb; }}
            .totals {{ margin-left: auto; width: 280px; }}
            .total-row {{ display: flex; justify-content: space-between; padding: 6px 0;
                         font-size: 13px; }}
            .total-row.grand {{ font-size: 18px; font-weight: 600; border-top: 2px solid #111;
                               padding-top: 10px; margin-top: 6px; }}
            .details-row {{ display: flex; gap: 40px; margin: 20px 0; }}
            .detail-item {{ }}
            .detail-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: #999; }}
            .detail-value {{ font-size: 13px; font-weight: 500; }}
            .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee;
                      font-size: 11px; color: #999; white-space: pre-line; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="sender">
                <div style="font-size:20px;font-weight:600;margin-bottom:8px;">
                    {ctx['sender_name'] or 'Invoice'}
                </div>
                <div class="party-detail">{ctx['sender_address']}</div>
                <div class="party-detail">{ctx['sender_email']}</div>
                {'<div class="party-detail">Tax ID: ' + ctx['sender_tax_id'] + '</div>' if ctx['sender_tax_id'] else ''}
            </div>
            <div class="invoice-meta">
                <p class="invoice-title">INVOICE</p>
                <p class="invoice-number">#{ctx['invoice_number']}</p>
                <span class="status-badge">{status}</span>
            </div>
        </div>

        <div class="parties">
            <div class="party">
                <div class="party-label">Bill to</div>
                <div class="party-name">{ctx['client_name']}</div>
                <div class="party-detail">{ctx['client_address']}</div>
                <div class="party-detail">{ctx['client_email']}</div>
                {'<div class="party-detail">Tax ID: ' + ctx['client_tax_id'] + '</div>' if ctx['client_tax_id'] else ''}
            </div>
        </div>

        <div class="details-row">
            <div class="detail-item">
                <div class="detail-label">Invoice Date</div>
                <div class="detail-value">{ctx['invoice_date']}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Due Date</div>
                <div class="detail-value">{ctx['due_date']}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Payment Terms</div>
                <div class="detail-value">{ctx['payment_terms'] or '—'}</div>
            </div>
            {'<div class="detail-item"><div class="detail-label">PO Number</div><div class="detail-value">' + ctx['po_number'] + '</div></div>' if ctx['po_number'] else ''}
        </div>

        <table>
            <thead>
                <tr>
                    <th style="width:40px;">#</th>
                    <th>Description</th>
                    <th style="width:60px;text-align:center;">Qty</th>
                    <th style="width:100px;text-align:right;">Rate</th>
                    <th style="width:100px;text-align:right;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
            </tbody>
        </table>

        <div class="totals">
            <div class="total-row">
                <span>Subtotal</span>
                <span>{symbol}{ctx['subtotal']:,.2f}</span>
            </div>
            {'<div class="total-row"><span>Tax (' + str(ctx["tax_rate"]) + '%)</span><span>' + symbol + f"{ctx['tax_amount']:,.2f}" + '</span></div>' if ctx['tax_rate'] else ''}
            <div class="total-row grand">
                <span>Total</span>
                <span>{symbol}{ctx['total']:,.2f}</span>
            </div>
        </div>

        {'<div class="footer">' + ctx['footer'] + '</div>' if ctx['footer'] else ''}
        <div class="footer">
            This invoice was generated by Kora (kora.app).
        </div>
    </body>
    </html>
    """

    # Render HTML to PDF
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf()
    except ImportError:
        # Fallback: try ReportLab if WeasyPrint is not installed
        # (simplified — ReportLab requires more manual layout)
        raise ImportError(
            "WeasyPrint required for invoice PDF generation. "
            "Install: pip install weasyprint --break-system-packages"
        )
```

---

## Invoice router additions

```python
# Add to routers/invoices.py:

@router.post("/{invoice_id}/pdf")
async def generate_pdf(invoice_id: str, user=Depends(get_current_user)):
    """Generate (or regenerate) the invoice PDF."""
    from app.services.invoice_pdf import generate_invoice_pdf
    gcs_path = await generate_invoice_pdf(user["id"], invoice_id)
    return {"pdf_path": gcs_path}

@router.get("/{invoice_id}/pdf/download")
async def download_pdf(invoice_id: str, user=Depends(get_current_user)):
    """Get a signed download URL for the invoice PDF."""
    from app.services.storage import get_signed_url
    invoice = store.get_invoice(user["id"], invoice_id)
    if not invoice or not invoice.get("pdf_path"):
        raise HTTPException(404, "Invoice PDF not found — generate it first")
    url = get_signed_url(
        user_id=user["id"],
        gcs_path=invoice["pdf_path"],
        expiry_minutes=15,
        filename_override=f"invoice-{invoice.get('invoice_number', invoice_id[:8])}.pdf",
    )
    return {"url": url, "expires_in_minutes": 15}
```

---

## Auto-generate PDF on invoice creation

```python
# In the create_invoice handler, after saving to DB:
# Generate PDF automatically so it's always ready for download

from app.services.invoice_pdf import generate_invoice_pdf

# After: invoice = store.create_invoice(user_id, invoice_data)
try:
    await generate_invoice_pdf(user["id"], invoice["id"])
except Exception as e:
    # PDF generation failure should not block invoice creation
    print(f"Invoice PDF generation failed: {e}")
```

---

## GCS path convention for invoices

```
users/{user_id}/invoices/{invoice_id}.pdf
```

Add to `services/storage.py` if not already present:

```python
def invoice_path(user_id: str, invoice_id: str) -> str:
    return _user_path(user_id, "invoices", f"{invoice_id}.pdf")
```
