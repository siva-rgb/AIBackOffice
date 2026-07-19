---
name: kora-invoice-enhance
description: >
  Enhance Kora's invoice system: generate professional invoice PDFs, wire Resend
  for actual email delivery, add address fields, payment terms, tax IDs, and
  invoice date. Use this skill when building invoice PDF generation, wiring email
  sending for follow-ups, enhancing the invoice data model, or fixing invoice
  display/formatting. Triggers on: "invoice PDF", "send invoice email", "invoice
  address", "payment terms", "tax ID", "VAT", "GSTIN", "invoice enhancements",
  "download invoice", "invoice template".
---

# Kora Invoice Enhancements

> "An invoice that can't be downloaded or emailed isn't an invoice."

Two critical fixes + four credibility improvements. Follows existing codebase patterns.

Read the reference files in this order:
1. `references/schema.md`      — column additions + new model fields
2. `references/pdf.md`         — invoice PDF generation using existing pdf_generator patterns
3. `references/email.md`       — Resend wiring for actual email delivery
4. `references/frontend.md`    — UI changes for new fields + PDF download

---

## 1. What this fixes

| Priority | Gap | Fix |
|---|---|---|
| **P0** | No invoice PDF | Generate professional PDF with ReportLab/WeasyPrint |
| **P0** | Emails never send | Wire Resend SDK, send follow-ups for real |
| **P1** | No sender address | Add address fields to user profile |
| **P1** | No client address | Add billing address to invoice + client |
| **P1** | No payment terms | Add `payment_terms` field (Net 14, Net 30, etc.) |
| **P1** | No invoice date | Add `invoice_date` distinct from `created_at` |
| **P2** | No tax ID / VAT | Add optional `tax_id` to user profile + `client_tax_id` to invoice |
| **P2** | No PO number | Add optional `po_number` field |

---

## 2. Codebase patterns (follow exactly)

- **Models:** Pydantic v2 `CamelModel` with camelCase aliases
- **Store:** `store.py` dispatcher → both `memory_store.py` and `supabase_store.py`
- **PDF generation:** existing `services/pdf_generator.py` already handles P&L and contracts — extend for invoices using the same patterns (ReportLab or WeasyPrint, whichever is used)
- **Email:** Resend Python SDK (`resend` package, already in requirements)
- **Cloud Storage:** use `services/storage.py` helpers to upload PDF + get signed URL
- **Agent logging:** log every email send to `agent_logs`
- **No FK columns on existing tables** — Kora convention

---

## 3. Build order

**Phase 1 — Schema changes (1 hour)**
Add columns to invoices, users, clients. Apply migration.
Read `references/schema.md`.

**Phase 2 — Invoice PDF generation (half day)**
Build the PDF template. Wire into the invoice router.
Store PDF in GCS. Return signed download URL.
Read `references/pdf.md`.

**Phase 3 — Resend email wiring (half day)**
Wire Resend SDK. Send invoice emails + follow-up emails for real.
Log every send to agent_logs.
Read `references/email.md`.

**Phase 4 — Frontend (half day)**
Add address fields to invoice form. Show payment terms selector.
Add PDF download button. Show email delivery status.
Read `references/frontend.md`.

---

## 4. New files / modified files

```
New:
  backend/app/services/invoice_pdf.py    — invoice PDF generation
  backend/app/services/email_service.py  — Resend wrapper (if not already present)

Modified:
  backend/app/models.py                  — add fields to Invoice model
  backend/app/backends/memory_store.py   — update invoice helpers
  backend/app/backends/supabase_store.py — update invoice helpers
  backend/app/routers/invoices.py        — add PDF + send endpoints
  backend/app/services/invoice_agent.py  — wire email sending into follow-up logic
  frontend: invoice form + detail page   — new fields + download button
```
