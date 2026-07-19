# Invoice Enhancements — Schema Reference

All columns are nullable and backward compatible. Existing invoices continue to work.

---

## Migration SQL

```sql
-- ── Invoice table additions ──────────────────────────────────────────────────

-- Invoice date (distinct from created_at — the date printed on the invoice)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS invoice_date DATE;
-- Backfill: UPDATE invoices SET invoice_date = created_at::date WHERE invoice_date IS NULL;

-- Payment terms (human-readable + days)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_terms TEXT;
-- Values: "Net 14", "Net 30", "Net 60", "Due on receipt", "Custom"
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_terms_days INTEGER;
-- Computed from payment_terms: 14, 30, 60, 0, null

-- Client billing address
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS client_address TEXT;
-- Full address as one text block: "123 Main St\nSan Francisco, CA 94102\nUSA"

-- Client tax ID (for B2B, EU VAT, India GSTIN)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS client_tax_id TEXT;

-- PO / reference number (optional, for B2B clients who require it)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS po_number TEXT;

-- PDF storage path (GCS path, not a URL)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS pdf_path TEXT;

-- Email delivery tracking
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS email_message_id TEXT;
-- Resend returns a message ID — store it for delivery tracking

-- Amount paid (for future partial payment support — default to 0 for now)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS amount_paid NUMERIC(12,2) DEFAULT 0;

-- ── User profile additions (sender address on invoices) ──────────────────────

ALTER TABLE users ADD COLUMN IF NOT EXISTS business_address TEXT;
-- Full address: "456 Oak Ave\nMumbai, Maharashtra 400001\nIndia"

ALTER TABLE users ADD COLUMN IF NOT EXISTS tax_id TEXT;
-- Tax ID / VAT / GSTIN / ABN — whatever is relevant for the user's jurisdiction

ALTER TABLE users ADD COLUMN IF NOT EXISTS invoice_footer TEXT;
-- Optional footer text: bank details, payment instructions, legal notice

-- ── Client table additions (default billing address) ─────────────────────────

ALTER TABLE clients ADD COLUMN IF NOT EXISTS billing_address TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS tax_id TEXT;
```

---

## Model additions (add to `app/models.py`)

```python
# Add these fields to the existing Invoice model (extend, don't replace):

class InvoiceCreate(CamelModel):
    # ... existing fields ...
    invoice_date: str | None = None          # ISO date, defaults to today
    payment_terms: str | None = "Net 14"     # "Net 14", "Net 30", "Due on receipt"
    payment_terms_days: int | None = 14
    client_address: str | None = None
    client_tax_id: str | None = None
    po_number: str | None = None

class InvoiceResponse(CamelModel):
    # ... existing fields ...
    invoice_date: str | None = None
    payment_terms: str | None = None
    payment_terms_days: int | None = None
    client_address: str | None = None
    client_tax_id: str | None = None
    po_number: str | None = None
    pdf_path: str | None = None
    email_message_id: str | None = None
    amount_paid: float = 0

# Add to UserProfile or wherever the user's business info is stored:
class UserProfileUpdate(CamelModel):
    # ... existing fields ...
    business_address: str | None = None
    tax_id: str | None = None
    invoice_footer: str | None = None
```

---

## Store helper additions

```python
# In both memory_store.py and supabase_store.py:

def update_invoice_pdf(user_id: str, invoice_id: str, pdf_path: str):
    """Store the GCS path of the generated invoice PDF."""
    # supabase:
    return sb().table("invoices").update({
        "pdf_path": pdf_path
    }).eq("id", invoice_id).eq("user_id", user_id).execute().data[0]

def update_invoice_email(user_id: str, invoice_id: str, message_id: str):
    """Store the Resend message ID after sending."""
    return sb().table("invoices").update({
        "email_message_id": message_id,
        "sent_at": "now()",
        "status": "sent",
    }).eq("id", invoice_id).eq("user_id", user_id).execute().data[0]
```

---

## Payment terms helper

```python
# In models.py or a utils file:

PAYMENT_TERMS_MAP = {
    "Due on receipt": 0,
    "Net 7": 7,
    "Net 14": 14,
    "Net 21": 21,
    "Net 30": 30,
    "Net 45": 45,
    "Net 60": 60,
}

def compute_due_date(invoice_date: str, payment_terms: str) -> str:
    """Compute due_date from invoice_date + payment_terms."""
    from datetime import date, timedelta
    d = date.fromisoformat(invoice_date)
    days = PAYMENT_TERMS_MAP.get(payment_terms, 14)
    return (d + timedelta(days=days)).isoformat()
```

---

## Auto-fill from client record

When creating an invoice for a known client, pre-fill address and tax_id:

```python
# In the invoice creation handler:
if client_id:
    client = store.get_client(user_id, client_id)
    if client:
        if not body.client_address and client.get("billing_address"):
            body.client_address = client["billing_address"]
        if not body.client_tax_id and client.get("tax_id"):
            body.client_tax_id = client["tax_id"]
```
