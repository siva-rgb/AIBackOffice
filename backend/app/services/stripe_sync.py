from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import stripe

from app import store
from app.models import Transaction
from app.services.agent_logger import log_action
from app.services.invoice_payments import from_minor_units, record_payment_received

# Pull transactions from a user's connected Stripe account and normalize
# into Kora's Transaction format. Pre-categorized from Stripe's typed data —
# no LLM call needed. Same output shape as CSV / PDF upload.


async def sync_stripe_transactions(user_id: str, days_back: int = 30) -> dict:
    start = datetime.now(timezone.utc)

    conn = store.get_stripe_connection(user_id)
    if not conn or not conn.get("connected"):
        return {"error": "Stripe not connected", "transactions": [], "synced_count": 0}

    account_id = conn["stripe_account_id"]
    platform_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not platform_key:
        return {"error": "Stripe not configured on the server", "transactions": [], "synced_count": 0}

    since = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp())

    try:
        all_btxns = []
        has_more = True
        starting_after = conn.get("sync_cursor")

        while has_more:
            params: dict = {
                "limit": 100,
                "created": {"gte": since},
                "stripe_account": account_id,
                "api_key": platform_key,
            }
            if starting_after:
                params["starting_after"] = starting_after

            page = stripe.BalanceTransaction.list(**params)
            all_btxns.extend(page.data)
            has_more = page.has_more
            if page.data:
                starting_after = page.data[-1].id
            if len(all_btxns) >= 500:
                break

        now = datetime.now(timezone.utc).isoformat()
        raw_rows = _normalize(all_btxns, account_id, platform_key)

        # Build Transaction objects and dedup-insert via the existing store
        candidate = [
            Transaction(
                id=store.uid("tx"),
                user_id=user_id,
                date=r["date"],
                description=r["description"],
                amount=r["amount"],
                currency=r["currency"],
                type=r["type"],
                category=r["category"],
                source="stripe_connect",
                ai_categorized=True,
                ai_confidence=0.95,
                raw_text=r["raw_text"],
                # Stripe's own id for this movement. It is what makes two
                # identical same-day payments two rows instead of one.
                external_id=r.get("stripe_id") or None,
                created_at=now,
            )
            for r in raw_rows
        ]

        inserted = store.insert_transactions(candidate)
        settled = _settle_linked_invoices(user_id, inserted, raw_rows)

        store.update_stripe_connection(
            user_id,
            {
                "last_sync_at": now,
                "last_sync_txn_count": len(inserted),
                "sync_cursor": starting_after,
                "last_error": None,
            },
        )

        latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        log_action(
            user_id=user_id,
            agent_type="billing",
            action=f"Synced {len(inserted)} transactions from Stripe Connect",
            input={"account_id": account_id, "days_back": days_back},
            output={"inserted": len(inserted), "fetched": len(raw_rows)},
            latency_ms=latency_ms,
            triggered_by="user",
        )

        return {
            "transactions": [_txn_to_dict(t) for t in inserted],
            "source": "stripe_connect",
            "account_email": conn.get("stripe_email", ""),
            "synced_count": len(inserted),
            "invoices_settled": settled,
            "duplicates_skipped": len(candidate) - len(inserted),
        }

    except stripe.error.StripeError as e:
        store.update_stripe_connection(user_id, {"last_error": str(e)})
        return {"error": f"Stripe API error: {str(e)}", "transactions": [], "synced_count": 0}


def _settle_linked_invoices(user_id: str, inserted: list, raw_rows: list[dict]) -> int:
    """Tie each imported payment to the invoice it settled, and claim it.

    Two things happen per linked transaction, and the second matters more than
    the first:

      1. The invoice is marked paid if it is still open. That is the safety net
         for a deployment whose Stripe webhook is not wired for Connect events —
         the payment still lands correctly, just at sync time rather than
         instantly.

      2. The transaction id is recorded as reconciled. `reconcile_payments`
         reads exactly this marker to build its "already consumed" set, so
         without it a payment for invoice A stays in the pool and can be matched
         against a different open invoice B with the same client and amount.

    Matched on (date, description, amount) because that is the key
    `insert_transactions` deduplicates on, so it is the only key guaranteed to
    line an inserted row up with the row it came from.
    """
    if not inserted:
        return 0
    by_key = {(r["date"], r["description"], round(float(r["amount"]), 2)): r for r in raw_rows}
    settled = 0

    for txn in inserted:
        row = by_key.get((txn.date, txn.description, round(float(txn.amount), 2)))
        invoice_id = (row or {}).get("invoice_id")
        if not invoice_id:
            continue
        try:
            invoice = store.get_invoice(user_id, invoice_id)
            if not invoice:
                continue
            if invoice.status not in ("paid", "cancelled"):
                store.update_invoice(
                    user_id,
                    invoice_id,
                    {
                        "status": "paid",
                        "paid_at": datetime.now(timezone.utc).isoformat(),
                        "amount_paid": float(invoice.total),
                    },
                )
                # Only on the transition, so the webhook and this sync cannot
                # both announce the same payment.
                record_payment_received(user_id, invoice, "Stripe")
            log_action(
                user_id=user_id,
                agent_type="cross_module",
                action=f"Stripe payment matched to invoice {invoice.invoice_number}",
                output={
                    # The key reconcile_payments looks for. Renaming it silently
                    # un-claims every payment this path settles.
                    "reconciledTransactionId": txn.id,
                    "invoiceId": invoice_id,
                    "matchedBy": "stripe_payment_link_metadata",
                },
                triggered_by="cross_module",
            )
            settled += 1
        except Exception as exc:  # pragma: no cover - one bad row must not stop the sync
            print(f"[stripe-sync] could not settle invoice {invoice_id}: {type(exc).__name__}: {str(exc)[:100]}")
    return settled


def _normalize(balance_txns: list, account_id: str, platform_key: str) -> list[dict]:
    rows = []
    for bt in balance_txns:
        stripe_type = bt.get("type", "")
        description = bt.get("description") or ""
        amount_cents = bt.get("amount", 0)
        currency = (bt.get("currency") or "usd").upper()
        # Not /100. Stripe reports in the currency's smallest unit, which is the
        # whole yen for JPY and a thousandth for BHD — dividing everything by a
        # hundred books a 5,000 yen payment as 50 yen.
        amount = from_minor_units(amount_cents, currency)

        if stripe_type == "charge":
            kora_type = "income"
            category = "client_payment"
            description = description or "Stripe payment"

        elif stripe_type == "payout":
            # Payouts move money to the bank — not income/expense, just a transfer. Skip.
            continue

        elif stripe_type == "refund":
            kora_type = "expense"
            category = "refund_given"
            amount = -abs(amount)
            description = description or "Stripe refund"

        elif stripe_type == "stripe_fee":
            kora_type = "expense"
            category = "bank_fees"
            amount = -abs(amount)
            description = description or "Stripe processing fee"

        elif stripe_type == "adjustment":
            kora_type = "income" if amount >= 0 else "expense"
            category = "other_income" if amount >= 0 else "other_expense"
            description = description or "Stripe adjustment"

        elif stripe_type in ("transfer", "transfer_reversal"):
            continue

        else:
            if amount == 0:
                continue
            kora_type = "income" if amount > 0 else "expense"
            category = "other_income" if amount > 0 else "other_expense"

        created = bt.get("created", 0)
        date_str = datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d") if created else datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Enrich with the customer name, and pick up the invoice this charge
        # settled if it came from one of our Payment Links.
        ctx = _charge_context(bt, account_id, platform_key)
        if ctx["customer_name"]:
            description = f"{ctx['customer_name']} — {description}"

        rows.append(
            {
                "date": date_str,
                "description": description.strip(),
                "amount": amount,
                "type": kora_type,
                "currency": currency,
                "category": category,
                "raw_text": f"Stripe {stripe_type}: {bt.get('description') or ''}",
                # Not persisted on the Transaction — used after insert to settle
                # and claim the invoice this payment belongs to.
                "invoice_id": ctx["invoice_id"],
                "stripe_id": bt.get("id") or "",
            }
        )

    return rows


def _charge_context(bt: dict, account_id: str, platform_key: str) -> dict:
    """Billing name AND the Kora invoice this charge settled, in one retrieval.

    The invoice id is the important half. When a client pays through an invoice
    Payment Link, the webhook marks that invoice paid straight away — which took
    it out of `reconcile_payments`'s pool of open invoices, so the matching
    income transaction arrived later looking unclaimed. A freelancer with two
    open invoices to the same client for the same amount (a monthly retainer is
    exactly that shape) would then have the SECOND invoice marked paid off the
    back of a payment for the first.

    Carrying the invoice id through means the transaction can be tied to the
    invoice it actually paid, and claimed so nothing else can consume it.

    Metadata is read from the charge first and the PaymentIntent second: we set
    it via `payment_intent_data`, so the PaymentIntent is where it reliably
    lives, but a charge may carry its own copy and reading that avoids a second
    lookup. Best-effort throughout — a failure here degrades the description,
    it must never fail the sync.
    """
    out = {"customer_name": "", "invoice_id": ""}
    source = bt.get("source")
    if not source or not isinstance(source, str) or not source.startswith("ch_"):
        return out
    try:
        charge = stripe.Charge.retrieve(
            source,
            stripe_account=account_id,
            api_key=platform_key,
            expand=["payment_intent"],
        )
    except Exception:
        return out

    out["customer_name"] = (charge.get("billing_details") or {}).get("name") or ""

    meta = charge.get("metadata") or {}
    invoice_id = meta.get("kora_invoice_id")
    if not invoice_id:
        intent = charge.get("payment_intent")
        if isinstance(intent, dict):
            invoice_id = (intent.get("metadata") or {}).get("kora_invoice_id")
    out["invoice_id"] = invoice_id or ""
    return out


def _txn_to_dict(t: Transaction) -> dict:
    return {
        "id": t.id,
        "date": t.date,
        "description": t.description,
        "amount": t.amount,
        "type": t.type,
        "currency": t.currency,
        "category": t.category,
        "source": t.source,
    }
