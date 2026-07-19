from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import stripe

from app import store
from app.models import Transaction
from app.services.agent_logger import log_action

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
                created_at=now,
            )
            for r in raw_rows
        ]

        inserted = store.insert_transactions(candidate)

        store.update_stripe_connection(user_id, {
            "last_sync_at": now,
            "last_sync_txn_count": len(inserted),
            "sync_cursor": starting_after,
            "last_error": None,
        })

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
            "duplicates_skipped": len(candidate) - len(inserted),
        }

    except stripe.error.StripeError as e:
        store.update_stripe_connection(user_id, {"last_error": str(e)})
        return {"error": f"Stripe API error: {str(e)}", "transactions": [], "synced_count": 0}


def _normalize(balance_txns: list, account_id: str, platform_key: str) -> list[dict]:
    rows = []
    for bt in balance_txns:
        stripe_type = bt.get("type", "")
        description = bt.get("description") or ""
        amount_cents = bt.get("amount", 0)
        currency = (bt.get("currency") or "usd").upper()
        amount = round(amount_cents / 100, 2)

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
        date_str = (
            datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d")
            if created
            else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

        # Try to enrich with customer name from the charge object
        customer_name = _get_customer_name(bt, account_id, platform_key)
        if customer_name:
            description = f"{customer_name} — {description}"

        rows.append({
            "date": date_str,
            "description": description.strip(),
            "amount": amount,
            "type": kora_type,
            "currency": currency,
            "category": category,
            "raw_text": f"Stripe {stripe_type}: {bt.get('description') or ''}",
        })

    return rows


def _get_customer_name(bt: dict, account_id: str, platform_key: str) -> str:
    """Best-effort: pull billing name from the charge. Swallow all errors."""
    source = bt.get("source")
    if not source or not isinstance(source, str) or not source.startswith("ch_"):
        return ""
    try:
        charge = stripe.Charge.retrieve(
            source,
            stripe_account=account_id,
            api_key=platform_key,
        )
        return charge.get("billing_details", {}).get("name") or ""
    except Exception:
        return ""


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
