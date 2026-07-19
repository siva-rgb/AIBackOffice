# Stripe — Backend Implementation

FastAPI routes for Stripe Checkout, webhook handling, and plan enforcement.
All patterns match Kora's existing codebase (CamelModel, store.py, both backends).

---

## Checkout session creation

```python
# backend/app/routers/stripe_billing.py
import os
import stripe
from fastapi import APIRouter, Depends, Request, HTTPException
from app.dependencies import get_current_user
from app import store
from app.models import CamelModel
from pydantic import Field

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

router = APIRouter(prefix="/stripe", tags=["stripe"])


class CheckoutRequest(CamelModel):
    price_id: str = Field(..., min_length=1)
    success_url: str = Field(default="")
    cancel_url: str = Field(default="")


@router.post("/checkout")
async def create_checkout_session(
    body: CheckoutRequest,
    user=Depends(get_current_user),
):
    """
    Create a Stripe Checkout session. Frontend redirects the browser to the
    returned URL. Stripe handles the entire payment UI.
    """
    user_id = user["id"]
    user_data = store.get_user(user_id)
    email = user_data.get("email", "") if user_data else ""

    # Base URLs
    app_url = os.environ.get("NEXT_PUBLIC_APP_URL", "http://localhost:3000")
    success_url = body.success_url or f"{app_url}/settings/billing?success=true"
    cancel_url = body.cancel_url or f"{app_url}/pricing?cancelled=true"

    # Check if user already has a Stripe customer ID
    stripe_customer_id = (user_data or {}).get("stripe_customer_id")

    # Determine if this is a subscription or one-time purchase
    contract_price = os.environ.get("STRIPE_CONTRACT_PRICE_ID", "")
    is_one_time = body.price_id == contract_price

    try:
        session_params = {
            "payment_method_types": ["card"],
            "line_items": [{"price": body.price_id, "quantity": 1}],
            "mode": "payment" if is_one_time else "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": user_id,  # links session back to our user
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
    user_data = store.get_user(user["id"])
    if not user_data:
        return {"plan": "free", "subscription": None}

    plan = user_data.get("plan", "free")
    stripe_sub_id = user_data.get("stripe_subscription_id")

    subscription_info = None
    if stripe_sub_id:
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
        "stripe_customer_id": user_data.get("stripe_customer_id"),
    }


@router.post("/cancel")
async def cancel_subscription(user=Depends(get_current_user)):
    """Cancel subscription at end of current period."""
    user_data = store.get_user(user["id"])
    stripe_sub_id = (user_data or {}).get("stripe_subscription_id")
    if not stripe_sub_id:
        raise HTTPException(400, "No active subscription")

    try:
        sub = stripe.Subscription.modify(
            stripe_sub_id,
            cancel_at_period_end=True,
        )
        return {"cancelled_at_period_end": True, "period_end": sub.current_period_end}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {str(e)}")


@router.post("/reactivate")
async def reactivate_subscription(user=Depends(get_current_user)):
    """Reactivate a subscription that was set to cancel at period end."""
    user_data = store.get_user(user["id"])
    stripe_sub_id = (user_data or {}).get("stripe_subscription_id")
    if not stripe_sub_id:
        raise HTTPException(400, "No subscription found")

    try:
        sub = stripe.Subscription.modify(stripe_sub_id, cancel_at_period_end=False)
        return {"reactivated": True, "status": sub.status}
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {str(e)}")


class UpgradeRequest(CamelModel):
    new_price_id: str = Field(..., min_length=1)


@router.post("/upgrade")
async def upgrade_or_downgrade(body: UpgradeRequest, user=Depends(get_current_user)):
    """
    Change plan (Starter ↔ Pro) on an active subscription.
    Stripe prorates automatically — user pays the difference immediately
    on upgrade, or gets credit applied on downgrade.
    """
    user_data = store.get_user(user["id"])
    stripe_sub_id = (user_data or {}).get("stripe_subscription_id")
    if not stripe_sub_id:
        raise HTTPException(400, "No active subscription to change")

    try:
        # Get current subscription to find the item ID
        sub = stripe.Subscription.retrieve(stripe_sub_id)
        if not sub.items.data:
            raise HTTPException(400, "Subscription has no items")

        item_id = sub.items.data[0].id

        # Swap the price on the existing subscription
        updated = stripe.Subscription.modify(
            stripe_sub_id,
            items=[{
                "id": item_id,
                "price": body.new_price_id,
            }],
            proration_behavior="create_prorations",  # charge/credit difference immediately
        )

        # Determine new plan from price
        starter_price = os.environ.get("STRIPE_STARTER_PRICE_ID", "")
        pro_price = os.environ.get("STRIPE_PRO_PRICE_ID", "")
        new_plan = "pro" if body.new_price_id == pro_price else "starter"

        store.update_user(user["id"], {"plan": new_plan})

        _log_billing_event(
            user["id"],
            f"Plan changed to {new_plan}",
            {"old_plan": user_data.get("plan"), "new_plan": new_plan},
        )

        return {
            "plan": new_plan,
            "status": updated.status,
            "proration": True,
        }
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {str(e)}")


@router.post("/portal")
async def create_customer_portal(user=Depends(get_current_user)):
    """
    Create a Stripe Customer Portal session.
    The portal lets users update payment methods, view invoices/receipts,
    and manage their subscription — all hosted by Stripe.
    Frontend redirects to the returned URL.
    """
    user_data = store.get_user(user["id"])
    customer_id = (user_data or {}).get("stripe_customer_id")
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
```

---

## Billing event logger (every Stripe action → agent_logs)

```python
# Add to routers/stripe_billing.py — before the webhook handler

from app.services.agent_logger import log_agent_action
from app.models import AgentType

def _log_billing_event(user_id: str, action: str, data: dict):
    """Log a Stripe/billing event to agent_logs for audit trail."""
    try:
        log_agent_action(
            user_id=user_id,
            agent_type="billing",  # add 'billing' to AgentType enum
            action=action,
            input_data={},
            output_data=data,
            latency_ms=0,
            triggered_by="system",
        )
    except Exception:
        pass  # logging failure should never block billing operations
```

**Add `'billing'` to the agent_type CHECK constraint:**
```sql
ALTER TABLE agent_logs DROP CONSTRAINT IF EXISTS agent_logs_agent_type_check;
ALTER TABLE agent_logs ADD CONSTRAINT agent_logs_agent_type_check
  CHECK (agent_type IN (
    'bookkeeper','invoice_follow_up','contract_generator',
    'cashflow_forecaster','alert_generator','cross_module',
    'supervisor','chat','butler',
    'butler_gmail','butler_drive','butler_calendar',
    'meeting_agent','gmail_agent','calendar_agent',
    'playbook','billing'
  ));
```

---

## Webhook handler (CRITICAL — must receive raw body)

```python
# Add to the same file: routers/stripe_billing.py

@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events. This endpoint:
    1. Receives raw bytes (NOT parsed JSON)
    2. Verifies the Stripe signature
    3. Processes the event
    4. Returns 200 quickly (Stripe times out after 20 seconds)

    CRITICAL: This route must NOT have get_current_user dependency.
    Stripe calls this, not a logged-in user.
    """
    # 1. Get raw body as bytes — MUST be raw for signature verification
    body = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not sig_header:
        raise HTTPException(400, "Missing stripe-signature header")

    # 2. Verify signature — rejects forged webhooks
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

    # 3. Route event to handler
    event_type = event["type"]
    data = event["data"]["object"]

    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(data)

        elif event_type == "customer.subscription.created":
            await _handle_subscription_change(data)

        elif event_type == "customer.subscription.updated":
            await _handle_subscription_change(data)

        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(data)

        elif event_type == "invoice.payment_succeeded":
            await _handle_payment_succeeded(data)

        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(data)

    except Exception as e:
        # Log but don't return error — Stripe will retry on non-200
        print(f"Webhook handler error for {event_type}: {e}")

    # 4. Return 200 immediately
    return {"received": True}


async def _handle_checkout_completed(session: dict):
    """
    Checkout session completed — link Stripe customer to our user.
    For one-time purchases (contract doc), grant the purchase.
    For subscriptions, the subscription.created event handles plan update.
    """
    user_id = session.get("client_reference_id") or session.get("metadata", {}).get("user_id")
    if not user_id:
        return

    customer_id = session.get("customer")
    mode = session.get("mode")  # "subscription" or "payment"

    # Store Stripe customer ID on our user record
    if customer_id:
        store.update_user(user_id, {"stripe_customer_id": customer_id})

    # For one-time purchases (pay-per-doc)
    if mode == "payment":
        # Grant the user a contract generation credit
        user_data = store.get_user(user_id)
        credits = (user_data or {}).get("contract_credits", 0)
        store.update_user(user_id, {"contract_credits": credits + 1})

    _log_billing_event(user_id, f"Checkout completed ({mode})", {
        "customer_id": customer_id, "mode": mode,
    })


async def _handle_subscription_change(subscription: dict):
    """
    Subscription created or updated — set the user's plan based on the price.
    """
    customer_id = subscription.get("customer")
    if not customer_id:
        return

    # Find the user by stripe_customer_id
    user = store.get_user_by_stripe_customer(customer_id)
    if not user:
        return

    user_id = user["id"]
    sub_id = subscription.get("id")
    status = subscription.get("status")  # active, past_due, cancelled, etc.

    # Determine plan from the price ID
    items = subscription.get("items", {}).get("data", [])
    price_id = items[0]["price"]["id"] if items else ""

    starter_price = os.environ.get("STRIPE_STARTER_PRICE_ID", "")
    pro_price = os.environ.get("STRIPE_PRO_PRICE_ID", "")

    if status in ("active", "trialing"):
        if price_id == pro_price:
            plan = "pro"
        elif price_id == starter_price:
            plan = "starter"
        else:
            plan = "starter"  # default to starter for unknown prices
    else:
        plan = "free"  # past_due, cancelled, etc. → downgrade

    store.update_user(user_id, {
        "plan": plan,
        "stripe_subscription_id": sub_id,
    })

    _log_billing_event(user_id, f"Subscription {'created' if status == 'active' else 'updated'} → {plan}", {
        "plan": plan, "subscription_id": sub_id, "status": status, "price_id": price_id,
    })


async def _handle_subscription_deleted(subscription: dict):
    """Subscription cancelled — downgrade to free."""
    customer_id = subscription.get("customer")
    if not customer_id:
        return

    user = store.get_user_by_stripe_customer(customer_id)
    if not user:
        return

    store.update_user(user["id"], {
        "plan": "free",
        "stripe_subscription_id": None,
    })

    _log_billing_event(user["id"], "Subscription cancelled → downgraded to free", {
        "previous_subscription": subscription.get("id"),
    })


async def _handle_payment_succeeded(invoice: dict):
    """Invoice paid — confirm subscription is active."""
    # Usually handled by subscription.updated, but this is a safety net
    pass


async def _handle_payment_failed(invoice: dict):
    """Payment failed — could downgrade or notify user."""
    customer_id = invoice.get("customer")
    if not customer_id:
        return

    user = store.get_user_by_stripe_customer(customer_id)
    if not user:
        return

    # Create an alert for the user
    store.create_alert(user["id"], {
        "type": "payment_failed",
        "severity": "critical",
        "title": "Payment failed",
        "body": "Your subscription payment failed. Please update your payment method to avoid losing access.",
        "action_url": "/settings/billing",
    })

    _log_billing_event(user["id"], "Payment failed", {
        "invoice_id": invoice.get("id"),
    })
```

---

## Store helpers needed

```python
# ── supabase_store.py ─────────────────────────────────────────────────────

def get_user_by_stripe_customer(customer_id: str) -> dict | None:
    """Find a user by their Stripe customer ID."""
    result = sb().table("users").select("*").eq(
        "stripe_customer_id", customer_id
    ).execute().data
    return result[0] if result else None


# ── memory_store.py ───────────────────────────────────────────────────────

def get_user_by_stripe_customer(customer_id: str) -> dict | None:
    """Find a user by their Stripe customer ID (in-memory mock)."""
    for user in _users.values():
        if user.get("stripe_customer_id") == customer_id:
            return user
    return None
```

---

## Plan enforcement service

```python
# backend/app/services/billing.py
from app import store

PLAN_RANK = {"free": 0, "starter": 1, "pro": 2}

PLAN_LIMITS = {
    "free": {
        "transactions_per_month": 20,
        "contracts_per_month": 1,
        "invoice_followups": False,
        "cashflow_forecast": False,
        "butler_full": False,
        "morning_briefing": False,
        "proposals": False,
    },
    "starter": {
        "transactions_per_month": None,  # unlimited
        "contracts_per_month": None,     # unlimited
        "invoice_followups": True,
        "cashflow_forecast": False,
        "butler_full": False,
        "morning_briefing": True,
        "proposals": False,
    },
    "pro": {
        "transactions_per_month": None,
        "contracts_per_month": None,
        "invoice_followups": True,
        "cashflow_forecast": True,
        "butler_full": True,
        "morning_briefing": True,
        "proposals": True,
    },
}


def get_user_plan(user_id: str) -> str:
    """
    Get the user's current plan from the database.
    ALWAYS read from DB — never trust client-supplied plan values.
    """
    user = store.get_user(user_id)
    if not user:
        return "free"
    return user.get("plan", "free")


def require_plan(user_id: str, min_plan: str) -> dict:
    """
    Check if user's plan meets the minimum requirement.
    Returns {allowed: bool, current_plan: str, required_plan: str}.
    """
    current = get_user_plan(user_id)
    return {
        "allowed": PLAN_RANK.get(current, 0) >= PLAN_RANK.get(min_plan, 0),
        "current_plan": current,
        "required_plan": min_plan,
    }


def check_feature(user_id: str, feature: str) -> bool:
    """Check if user's plan includes a specific feature."""
    plan = get_user_plan(user_id)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    return bool(limits.get(feature, False))


def check_transaction_limit(user_id: str) -> dict:
    """Check if user has hit their monthly transaction upload limit."""
    plan = get_user_plan(user_id)
    limit = PLAN_LIMITS[plan]["transactions_per_month"]
    if limit is None:
        return {"allowed": True, "limit": None, "used": 0}

    # Count transactions created this month
    from datetime import datetime
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0).isoformat()
    transactions = store.list_transactions(user_id)
    this_month = [t for t in transactions if t.get("created_at", "") >= month_start]
    used = len(this_month)

    return {
        "allowed": used < limit,
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
    }
```

---

## FastAPI dependency for plan gating

```python
# backend/app/dependencies.py — add plan gate dependency

from fastapi import HTTPException
from app.services.billing import require_plan as _require_plan

def require_starter(user=Depends(get_current_user)):
    """Dependency that requires Starter plan or above."""
    result = _require_plan(user["id"], "starter")
    if not result["allowed"]:
        raise HTTPException(403, detail={
            "error": "upgrade_required",
            "message": "This feature requires a Starter plan or above.",
            "current_plan": result["current_plan"],
            "required_plan": result["required_plan"],
            "upgrade_url": "/pricing",
        })
    return user

def require_pro(user=Depends(get_current_user)):
    """Dependency that requires Pro plan."""
    result = _require_plan(user["id"], "pro")
    if not result["allowed"]:
        raise HTTPException(403, detail={
            "error": "upgrade_required",
            "message": "This feature requires a Pro plan.",
            "current_plan": result["current_plan"],
            "required_plan": result["required_plan"],
            "upgrade_url": "/pricing",
        })
    return user

# Usage in routes:
# @router.post("/contracts/generate")
# async def generate_contract(user=Depends(require_pro)):
#     ...  # only Pro users reach this code
```

---

## Column additions to users table

```sql
-- These may already exist from the original schema.
-- Run as IF NOT EXISTS to be safe:

ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free'
  CHECK (plan IN ('free', 'starter', 'pro'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS contract_credits INTEGER DEFAULT 0;
```

---

## Register the router

```python
# In app/main.py, add:
from app.routers.stripe_billing import router as stripe_router
app.include_router(stripe_router, prefix="/api")
```
