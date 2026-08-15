from __future__ import annotations

import os
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from app.dependencies import get_current_user
from app import store
from app.models import Alert, CamelModel
from app.services.agent_logger import log_action

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

router = APIRouter(prefix="/api/stripe", tags=["stripe"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_billing_event(user_id: str, action: str, data: dict) -> None:
    try:
        log_action(
            user_id=user_id,
            agent_type="billing",
            action=action,
            input=None,
            output=data,
            model_used="none",
            triggered_by="system",
        )
    except Exception:
        pass


# ── Request bodies ────────────────────────────────────────────────────────────


class CheckoutRequest(CamelModel):
    price_id: str = Field(..., min_length=1)
    success_url: str = Field(default="")
    cancel_url: str = Field(default="")


class UpgradeRequest(CamelModel):
    new_price_id: str = Field(..., min_length=1)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/checkout")
async def create_checkout_session(
    body: CheckoutRequest,
    user=Depends(get_current_user),
):
    """Create a Stripe Checkout session; frontend redirects browser to returned URL."""
    user_id = user.id
    user_data = store.get_user(user_id)
    email = user_data.email if user_data else ""

    app_url = os.environ.get("NEXT_PUBLIC_APP_URL", "http://localhost:3000")
    success_url = body.success_url or f"{app_url}/settings/billing?success=true"
    cancel_url = body.cancel_url or f"{app_url}/pricing?cancelled=true"

    stripe_customer_id = user_data.stripe_customer_id if user_data else None

    contract_price = os.environ.get("STRIPE_CONTRACT_PRICE_ID", "")
    is_one_time = body.price_id == contract_price

    try:
        session_params: dict = {
            "payment_method_types": ["card"],
            "line_items": [{"price": body.price_id, "quantity": 1}],
            "mode": "payment" if is_one_time else "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": user_id,
            "metadata": {"user_id": user_id},
        }
        if stripe_customer_id:
            session_params["customer"] = stripe_customer_id
        else:
            session_params["customer_email"] = email

        session = stripe.checkout.Session.create(**session_params)
        return {"checkout_url": session.url, "session_id": session.id}

    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {str(e)}")


@router.get("/billing")
async def get_billing_info(user=Depends(get_current_user)):
    """Get current billing status for the settings page."""
    user_data = store.get_user(user.id)
    if not user_data:
        return {"plan": "free", "subscription": None}

    plan = user_data.plan
    stripe_sub_id = user_data.stripe_subscription_id

    subscription_info = None
    if stripe_sub_id and stripe.api_key:
        try:
            sub = stripe.Subscription.retrieve(stripe_sub_id)
            subscription_info = {
                "id": sub.id,
                "status": sub.status,
                "current_period_end": sub.current_period_end,
                "cancel_at_period_end": sub.cancel_at_period_end,
                "plan_amount": sub.items.data[0].price.unit_amount / 100 if sub.items.data else 0,
            }
        except stripe.error.StripeError:
            pass

    return {
        "plan": plan,
        "subscription": subscription_info,
        "stripe_customer_id": user_data.stripe_customer_id,
    }


@router.post("/cancel")
async def cancel_subscription(user=Depends(get_current_user)):
    """Cancel subscription at end of current period."""
    user_data = store.get_user(user.id)
    stripe_sub_id = user_data.stripe_subscription_id if user_data else None
    if not stripe_sub_id:
        raise HTTPException(400, "No active subscription")

    try:
        sub = stripe.Subscription.modify(stripe_sub_id, cancel_at_period_end=True)
        _log_billing_event(
            user.id,
            "Subscription set to cancel at period end",
            {
                "subscription_id": stripe_sub_id,
                "period_end": sub.current_period_end,
            },
        )
        return {"cancelled_at_period_end": True, "period_end": sub.current_period_end}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {str(e)}")


@router.post("/reactivate")
async def reactivate_subscription(user=Depends(get_current_user)):
    """Reactivate a subscription that was set to cancel at period end."""
    user_data = store.get_user(user.id)
    stripe_sub_id = user_data.stripe_subscription_id if user_data else None
    if not stripe_sub_id:
        raise HTTPException(400, "No subscription found")

    try:
        sub = stripe.Subscription.modify(stripe_sub_id, cancel_at_period_end=False)
        _log_billing_event(user.id, "Subscription reactivated", {"subscription_id": stripe_sub_id})
        return {"reactivated": True, "status": sub.status}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {str(e)}")


@router.post("/upgrade")
async def upgrade_or_downgrade(body: UpgradeRequest, user=Depends(get_current_user)):
    """Change plan on an active subscription (proration applied automatically)."""
    user_data = store.get_user(user.id)
    stripe_sub_id = user_data.stripe_subscription_id if user_data else None
    if not stripe_sub_id:
        raise HTTPException(400, "No active subscription to change")

    try:
        sub = stripe.Subscription.retrieve(stripe_sub_id)
        if not sub.items.data:
            raise HTTPException(400, "Subscription has no items")

        item_id = sub.items.data[0].id
        updated = stripe.Subscription.modify(
            stripe_sub_id,
            items=[{"id": item_id, "price": body.new_price_id}],
            proration_behavior="create_prorations",
        )

        pro_price = os.environ.get("STRIPE_PRO_PRICE_ID", "")
        new_plan = "pro" if body.new_price_id == pro_price else "starter"

        old_plan = user_data.plan if user_data else "free"
        store.update_user(user.id, {"plan": new_plan})

        _log_billing_event(
            user.id,
            f"Plan changed to {new_plan}",
            {
                "old_plan": old_plan,
                "new_plan": new_plan,
                "subscription_id": stripe_sub_id,
            },
        )

        return {"plan": new_plan, "status": updated.status, "proration": True}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {str(e)}")


@router.post("/portal")
async def create_customer_portal(user=Depends(get_current_user)):
    """Create a Stripe Customer Portal session for payment method management."""
    user_data = store.get_user(user.id)
    customer_id = user_data.stripe_customer_id if user_data else None
    if not customer_id:
        raise HTTPException(400, "No billing account found — subscribe first")

    app_url = os.environ.get("NEXT_PUBLIC_APP_URL", "http://localhost:3000")

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{app_url}/settings/billing",
        )
        return {"portal_url": session.url}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {str(e)}")


# ── Webhook ───────────────────────────────────────────────────────────────────


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Receives Stripe webhook events. Must use raw body for signature verification.
    No auth dependency — Stripe calls this directly.
    """
    body = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not sig_header:
        raise HTTPException(400, "Missing stripe-signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload=body,
            sig_header=sig_header,
            secret=webhook_secret,
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {str(e)}")

    event_type = event["type"]
    data = event["data"]["object"]

    try:
        if event_type == "checkout.session.completed":
            # Two different things produce this event and they must not be
            # confused. A subscription checkout runs on THIS platform account;
            # an invoice payment runs on the user's CONNECTED account and
            # carries kora_invoice_id. Both can be mode="payment", and the
            # platform branch grants a contract credit — so routing on mode
            # alone would hand out a free contract every time someone's client
            # paid an invoice.
            if (data.get("metadata") or {}).get("kora_invoice_id"):
                await _handle_invoice_payment(data, event.get("account"))
            else:
                await _handle_checkout_completed(data)
        elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
            await _handle_subscription_change(data)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(data)
        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(data)
    except Exception as e:
        print(f"[stripe-webhook] handler error for {event_type}: {e}")

    return {"received": True}


async def _handle_invoice_payment(session: dict, account_id: str | None) -> None:
    """A client paid one of the user's invoices through its Pay Now link.

    Idempotent by construction: the invoice is SET to fully paid rather than
    having the received amount added to `amount_paid`. Stripe delivers webhooks
    at least once, and an increment would double-count a redelivery. Setting is
    correct here because the Payment Link is created for exactly the amount
    outstanding, so a completed session settles the invoice by definition.
    """
    meta = session.get("metadata") or {}
    user_id = meta.get("kora_user_id")
    invoice_id = meta.get("kora_invoice_id")
    if not user_id or not invoice_id:
        return

    invoice = store.get_invoice(user_id, invoice_id)
    if not invoice:
        print(f"[stripe-webhook] payment for unknown invoice {invoice_id}")
        return
    if invoice.status in ("paid", "cancelled"):
        return  # already settled, or a redelivery

    store.update_invoice(
        user_id,
        invoice_id,
        {
            "status": "paid",
            "paid_at": _now(),
            "amount_paid": float(invoice.total),
        },
    )
    _log_billing_event(
        user_id,
        f"Invoice {invoice.invoice_number} paid via Stripe",
        {
            "invoice_id": invoice_id,
            "amount_total": session.get("amount_total"),
            "currency": session.get("currency"),
            "connected_account": account_id,
            "session_id": session.get("id"),
        },
    )


async def _handle_checkout_completed(session: dict) -> None:
    user_id = session.get("client_reference_id") or session.get("metadata", {}).get("user_id")
    if not user_id:
        return

    customer_id = session.get("customer")
    mode = session.get("mode")

    if customer_id:
        store.update_user(user_id, {"stripe_customer_id": customer_id})

    if mode == "payment":
        user_data = store.get_user(user_id)
        credits = user_data.contract_credits if user_data else 0
        store.update_user(user_id, {"contract_credits": credits + 1})

    _log_billing_event(
        user_id,
        f"Checkout completed ({mode})",
        {
            "customer_id": customer_id,
            "mode": mode,
        },
    )


async def _handle_subscription_change(subscription: dict) -> None:
    customer_id = subscription.get("customer")
    if not customer_id:
        return

    user = store.get_user_by_stripe_customer(customer_id)
    if not user:
        return

    user_id = user.id
    sub_id = subscription.get("id")
    status = subscription.get("status")

    items = subscription.get("items", {}).get("data", [])
    price_id = items[0]["price"]["id"] if items else ""

    starter_price = os.environ.get("STRIPE_STARTER_PRICE_ID", "")  # noqa: F841
    pro_price = os.environ.get("STRIPE_PRO_PRICE_ID", "")

    if status in ("active", "trialing"):
        plan = "pro" if price_id == pro_price else "starter"
    else:
        plan = "free"

    store.update_user(user_id, {"plan": plan, "stripe_subscription_id": sub_id})

    _log_billing_event(
        user_id,
        f"Subscription {status} → plan={plan}",
        {
            "plan": plan,
            "subscription_id": sub_id,
            "status": status,
            "price_id": price_id,
        },
    )


async def _handle_subscription_deleted(subscription: dict) -> None:
    customer_id = subscription.get("customer")
    if not customer_id:
        return

    user = store.get_user_by_stripe_customer(customer_id)
    if not user:
        return

    store.update_user(user.id, {"plan": "free", "stripe_subscription_id": None})

    _log_billing_event(
        user.id,
        "Subscription cancelled → downgraded to free",
        {
            "previous_subscription": subscription.get("id"),
        },
    )


async def _handle_payment_failed(invoice: dict) -> None:
    customer_id = invoice.get("customer")
    if not customer_id:
        return

    user = store.get_user_by_stripe_customer(customer_id)
    if not user:
        return

    _fail_body = "Your subscription payment failed. Please update your payment method to avoid losing access."
    try:
        store.insert_alert(
            Alert(
                id=store.uid("alert"),
                user_id=user.id,
                type="payment_failed",
                severity="critical",
                title="Payment failed",
                body=_fail_body,
                action_label="Manage billing",
                action_url="/settings/billing",
                read=False,
                created_at=_now(),
            )
        )
    except Exception:
        pass
    # Email the owner immediately — a failed payment is time-sensitive.
    try:
        from app.services import owner_notify

        owner_notify.notify_critical_alert(user.id, title="Payment failed", body=_fail_body, action_url="/settings/billing")
    except Exception:
        pass

    _log_billing_event(user.id, "Payment failed", {"invoice_id": invoice.get("id")})
