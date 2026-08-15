"""Real "Pay now" links for invoices, charged to the user's own Stripe account.

Before this, `send_invoice` fabricated a URL when none existed:

    payment_link = inv.payment_link or f"https://pay.stripe.com/demo/{number}"

`pay.stripe.com/demo/…` is not a Stripe endpoint. Every invoice this app has
ever sent carried a Pay Now button that goes nowhere — the worst possible place
for a dead link, since it is the one part of the email the recipient is asked to
click, and it fails in front of the user's own customer.

The rule this module follows is therefore: **never invent a link.** When a real
one cannot be created it returns None, the Pay Now button is omitted from the
email (`email_service` already guards on that), and the invoice still sends with
its PDF. An invoice without a payment button is a small inconvenience; one with
a broken button costs the user credibility with a client.

## Payment Links, not Checkout Sessions

A Checkout Session expires within 24 hours. The follow-up agent chases unpaid
invoices on days 3, 7 and 14, so a session-based link would be dead in every
chase email — the exact messages most likely to be acted on. Payment Links do
not expire, so one link stays valid for the life of the invoice.

## Direct charges

The link is created ON the connected account (`stripe_account=acct_…`), so the
money moves straight to the user, the client sees the user's business name on
the payment page, and this platform never touches the funds.
"""

from __future__ import annotations

import stripe

from .. import store
from ..config import settings

# Stripe expects amounts in the smallest unit of the currency, which is NOT
# always 1/100. Charging a JPY invoice as if it had cents overcharges the payer
# by 100×; treating BHD as two-decimal undercharges by 10×. Both lists are
# fixed by Stripe.
_ZERO_DECIMAL = {
    "bif",
    "clp",
    "djf",
    "gnf",
    "jpy",
    "kmf",
    "krw",
    "mga",
    "pyg",
    "rwf",
    "ugx",
    "vnd",
    "vuv",
    "xaf",
    "xof",
    "xpf",
}
_THREE_DECIMAL = {"bhd", "jod", "kwd", "omr", "tnd"}

# Links this app invented before real ones existed. Treated as absent so a
# previously "sent" invoice picks up a working link instead of keeping a dead
# one forever.
_PLACEHOLDER_PREFIXES = ("https://pay.stripe.com/demo/",)


def is_placeholder_link(url: str | None) -> bool:
    return bool(url) and url.startswith(_PLACEHOLDER_PREFIXES)


def to_minor_units(amount: float, currency: str) -> int:
    """Convert a decimal amount to the currency's smallest unit."""
    code = (currency or "usd").lower()
    if code in _ZERO_DECIMAL:
        return int(round(amount))
    if code in _THREE_DECIMAL:
        # Stripe requires three-decimal amounts to be an even multiple of 10.
        return int(round(amount * 1000 / 10)) * 10
    return int(round(amount * 100))


def from_minor_units(minor: int, currency: str) -> float:
    """Inverse of `to_minor_units` — Stripe's smallest unit back to a decimal.

    Dividing everything by 100 records a ¥5,000 charge as ¥50, understating the
    user's income by 99%. The same table governs both directions, so they cannot
    drift apart.
    """
    code = (currency or "usd").lower()
    if code in _ZERO_DECIMAL:
        return float(minor)
    if code in _THREE_DECIMAL:
        return round(minor / 1000, 3)
    return round(minor / 100, 2)


def outstanding_amount(invoice) -> float:
    """What is actually still owed — never the full total on a part-paid invoice."""
    total = float(getattr(invoice, "total", 0) or 0)
    paid = float(getattr(invoice, "amount_paid", 0) or 0)
    return round(max(total - paid, 0.0), 2)


class PaymentLinkUnavailable(Exception):
    """Carries a reason the caller can show the user verbatim."""


def record_payment_received(user_id: str, invoice, via: str) -> None:
    """Raise the "Payment received" alert for an invoice settled through Stripe.

    `reconcile_payments` has always raised this when it matched a bank payment
    to an invoice, and it is how a user finds out they have been paid. Payment
    links settle invoices on two newer paths — the webhook and the sync — and
    neither went through that function, so the invoice quietly flipped to paid
    and stopped being chased with nothing telling anyone.

    Called only from the branch that actually transitions the invoice, so the
    webhook and the sync cannot both announce the same payment.
    """
    from datetime import datetime, timezone

    from ..models import Alert

    try:
        store.insert_alert(
            Alert(
                id=store.uid("alert"),
                user_id=user_id,
                type="payment_reconciled",
                severity="info",
                title="Payment received — invoice marked paid",
                body=(
                    f"{invoice.client_name} paid {invoice.currency} {float(invoice.total):,.2f} "
                    f"for {invoice.invoice_number} via {via}. Kora marked it paid and stopped follow-ups."
                ),
                action_label="View invoices",
                action_url="/invoices",
                read=False,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    except Exception as exc:  # pragma: no cover - a missed alert must not lose the payment
        print(f"[invoice-payments] could not raise payment alert: {type(exc).__name__}: {str(exc)[:100]}")


def _connected_account(user_id: str) -> str:
    conn = store.get_stripe_connection(user_id)
    if not conn or not conn.get("connected") or not conn.get("stripe_account_id"):
        raise PaymentLinkUnavailable("Connect your Stripe account in Settings to add a Pay Now button to invoices.")
    # A live-mode connected account cannot be charged with a test-mode platform
    # key. Stripe's own error for this is opaque; say which side is which.
    platform_live = not (settings.STRIPE_SECRET_KEY or "").startswith("sk_test")
    if bool(conn.get("livemode")) != platform_live:
        raise PaymentLinkUnavailable(
            "Your connected Stripe account is in "
            f"{'live' if conn.get('livemode') else 'test'} mode but this deployment is in "
            f"{'live' if platform_live else 'test'} mode. Reconnect Stripe from Settings."
        )
    return str(conn["stripe_account_id"])


def create_payment_link(user_id: str, invoice) -> str:
    """A permanent Stripe Payment Link for what this invoice still owes.

    Raises PaymentLinkUnavailable with a message meant for the user. Callers
    that must not fail (the send path) catch it and omit the button.
    """
    account = _connected_account(user_id)
    currency = (getattr(invoice, "currency", None) or "USD").lower()
    amount = outstanding_amount(invoice)
    if amount <= 0:
        raise PaymentLinkUnavailable("This invoice has nothing left to pay.")

    minor = to_minor_units(amount, currency)
    if minor <= 0:
        raise PaymentLinkUnavailable("The invoice amount is too small to charge.")

    number = getattr(invoice, "invoice_number", "") or ""
    # Metadata is how the webhook maps a completed payment back to the invoice.
    # Set on the link AND on the resulting PaymentIntent: the Checkout Session
    # copies the link's metadata, but only payment_intent_data reaches the
    # charge, and different event types read different objects.
    meta = {
        "kora_user_id": user_id,
        "kora_invoice_id": getattr(invoice, "id", ""),
        "kora_invoice_number": number,
    }

    try:
        price = stripe.Price.create(
            unit_amount=minor,
            currency=currency,
            product_data={"name": f"Invoice {number}".strip()},
            api_key=settings.STRIPE_SECRET_KEY,
            stripe_account=account,
        )
        link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            metadata=meta,
            payment_intent_data={"metadata": meta},
            api_key=settings.STRIPE_SECRET_KEY,
            stripe_account=account,
        )
    except stripe.error.StripeError as exc:
        raise PaymentLinkUnavailable(f"Stripe refused the request: {getattr(exc, 'user_message', None) or str(exc)[:160]}")

    return str(link.url)


def ensure_payment_link(user_id: str, invoice, persist: bool = True) -> str | None:
    """Reuse a real link, replace a fabricated one, return None if impossible.

    Never raises. Used by the send path and the follow-up agent, neither of
    which may fail because of billing setup — an invoice with no Pay Now button
    still reaches the client with its PDF, and a chase email is still worth
    sending without one.

    Persists a newly created link so the second call is free: the follow-up
    agent runs over every unpaid invoice on days 3, 7 and 14, and without this
    each pass would mint a fresh Payment Link for the same invoice.
    """
    existing = getattr(invoice, "payment_link", None)
    if existing and not is_placeholder_link(existing):
        return existing
    try:
        link = create_payment_link(user_id, invoice)
    except PaymentLinkUnavailable as exc:
        print(f"[invoice-payments] no link for {getattr(invoice, 'id', '?')}: {exc}")
        return None
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[invoice-payments] link creation failed: {type(exc).__name__}: {str(exc)[:120]}")
        return None

    if persist and getattr(invoice, "id", None):
        try:
            store.update_invoice(user_id, invoice.id, {"payment_link": link})
        except Exception as exc:  # pragma: no cover - a failed write is not fatal
            print(f"[invoice-payments] could not persist link: {type(exc).__name__}")
    return link
