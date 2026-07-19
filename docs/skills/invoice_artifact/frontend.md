# Invoice Enhancements — Frontend Reference

---

## Invoice creation form — new fields

Add these fields to the invoice creation / edit form:

```
Existing fields (keep):
  Client name, client email, line items, tax rate, due date

New fields to add:

  Invoice date:     Date picker, defaults to today
                    Label: "Invoice date"
                    Helper: "The date printed on the invoice"

  Payment terms:    Dropdown selector
                    Options: "Due on receipt" | "Net 7" | "Net 14" | "Net 21" |
                             "Net 30" | "Net 45" | "Net 60"
                    Default: "Net 14"
                    On change: auto-compute due_date from invoice_date + terms

  Client address:   Textarea (3 lines)
                    Label: "Client billing address"
                    Placeholder: "123 Main St\nCity, State ZIP\nCountry"
                    Auto-fill from client record if client_id is set

  PO number:        Text input (optional)
                    Label: "PO / Reference number"
                    Placeholder: "Optional — your client's purchase order number"
                    Helper: "Required by some enterprise clients"

  Client tax ID:    Text input (optional)
                    Label: "Client tax ID / VAT"
                    Placeholder: "Optional"
                    Auto-fill from client record if client_id is set
```

### Auto-compute due date from payment terms

```typescript
// When payment_terms changes, recompute due_date:
function computeDueDate(invoiceDate: string, terms: string): string {
  const daysMap: Record<string, number> = {
    "Due on receipt": 0,
    "Net 7": 7,
    "Net 14": 14,
    "Net 21": 21,
    "Net 30": 30,
    "Net 45": 45,
    "Net 60": 60,
  }
  const days = daysMap[terms] ?? 14
  const date = new Date(invoiceDate)
  date.setDate(date.getDate() + days)
  return date.toISOString().split("T")[0]
}

// In the form:
// onChange for payment_terms or invoice_date → setDueDate(computeDueDate(...))
```

---

## Invoice detail page — new elements

### PDF download button

```tsx
// Add alongside existing action buttons on the invoice detail page:

<button
  onClick={async () => {
    // Generate PDF if not already done
    if (!invoice.pdfPath) {
      await apiPost(`/invoices/${invoice.id}/pdf`, {})
    }
    // Get signed download URL
    const { url } = await apiGet<{ url: string }>(
      `/invoices/${invoice.id}/pdf/download`
    )
    window.open(url, "_blank")
  }}
  className="rounded-lg border px-4 py-2 text-sm font-medium"
>
  Download PDF
</button>
```

### Send invoice button

```tsx
// Replace the existing send button (which currently doesn't actually send):

<button
  onClick={async () => {
    setSending(true)
    try {
      const result = await apiPost(`/invoices/${invoice.id}/send`, {})
      if (result.success) {
        // Refresh invoice to show sent status
        router.refresh()
      } else {
        alert(`Failed to send: ${result.error}`)
      }
    } finally {
      setSending(false)
    }
  }}
  disabled={sending || invoice.status === "sent"}
  className="rounded-lg bg-primary px-4 py-2 text-sm font-medium
             text-primary-foreground disabled:opacity-50"
>
  {sending ? "Sending..." : invoice.status === "sent" ? "Sent ✓" : "Send to client"}
</button>
```

### Email delivery status

```tsx
// Show on the invoice detail page when status is "sent":

{invoice.status !== "draft" && (
  <div className="text-sm text-muted-foreground mt-2">
    {invoice.sentAt && (
      <span>
        Sent {new Date(invoice.sentAt).toLocaleDateString()} via email
        {invoice.emailMessageId && " ✓"}
      </span>
    )}
    {invoice.followUpCount > 0 && (
      <span className="ml-3">
        Follow-ups sent: {invoice.followUpCount}
        {invoice.lastFollowUpAt && ` (last: ${new Date(invoice.lastFollowUpAt).toLocaleDateString()})`}
      </span>
    )}
  </div>
)}
```

---

## User settings — sender details

Add a section in Settings for invoice sender information:

```
Invoice settings
─────────────────

Business address:   Textarea (3 lines)
                    Label: "Your business address (appears on invoices)"
                    Placeholder: "123 Oak Ave\nMumbai, MH 400001\nIndia"

Tax ID:             Text input
                    Label: "Tax ID / VAT / GSTIN"
                    Placeholder: "Optional — shown on invoices if set"

Invoice footer:     Textarea (2 lines)
                    Label: "Invoice footer"
                    Placeholder: "Bank details, payment instructions, or a thank you note"
                    Helper: "Appears at the bottom of every invoice PDF"
```

---

## TypeScript type updates (add to `lib/api/types.ts`)

```typescript
// Extend the existing Invoice type:
export interface Invoice {
  // ... existing fields ...
  invoiceDate: string | null
  paymentTerms: string | null
  paymentTermsDays: number | null
  clientAddress: string | null
  clientTaxId: string | null
  poNumber: string | null
  pdfPath: string | null
  emailMessageId: string | null
  amountPaid: number
}
```

---

## Invoice list page — add delivery indicator

In the invoice list table, add a column or indicator showing whether the
invoice was actually emailed:

```
Status badges (extend existing):
  draft     → gray "Draft"
  sent      → blue "Sent" (with ✓ if emailMessageId exists)
  viewed    → purple "Viewed"
  paid      → green "Paid"
  overdue   → red "Overdue"
  cancelled → gray "Cancelled"

Add a small email icon next to "Sent" status if emailMessageId exists,
indicating the email was actually delivered (not just marked as sent).
```
