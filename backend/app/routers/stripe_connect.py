from __future__ import annotations

import stripe
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from app.config import settings
from app.dependencies import get_current_user
from app.clients.pool import get_async_http
from app.services.oauth_state import issue_oauth_state, verify_oauth_state
from app.services.token_encryption import encrypt_token
from app.services.agent_logger import log_action
from app import store

router = APIRouter(prefix="/api/stripe-connect", tags=["stripe-connect"])


@router.get("/connect")
async def connect_stripe(user=Depends(get_current_user)):
    """Return the Stripe Connect OAuth URL. Frontend redirects the browser here."""
    if not settings.STRIPE_CONNECT_CLIENT_ID:
        raise HTTPException(500, "Stripe Connect not configured (STRIPE_CONNECT_CLIENT_ID missing)")

    auth_url = (
        "https://connect.stripe.com/oauth/authorize"
        "?response_type=code"
        f"&client_id={settings.STRIPE_CONNECT_CLIENT_ID}"
        "&scope=read_write"
        f"&state={issue_oauth_state(user.id)}"
        f"&redirect_uri={settings.STRIPE_CONNECT_REDIRECT_URI}"
    )
    return {"auth_url": auth_url}


@router.get("/callback")
async def stripe_connect_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """
    Stripe redirects here after the user grants / denies permission.
    state = signed OAuth token (set in /connect).
    This endpoint is called by the Next.js proxy at /api/auth/stripe/callback.
    """
    frontend_url = settings.NEXT_PUBLIC_APP_URL

    if error:
        return RedirectResponse(f"{frontend_url}/settings?stripe_connect_error={error}")

    if not code or not state:
        return RedirectResponse(f"{frontend_url}/settings?stripe_connect_error=missing_params")

    user_id = verify_oauth_state(state)
    if not user_id:
        return RedirectResponse(f"{frontend_url}/settings?stripe_connect_error=invalid_state")

    try:
        client = get_async_http()
        resp = await client.post(
            "https://connect.stripe.com/oauth/token",
            data={
                "client_secret": settings.STRIPE_SECRET_KEY,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )
        data = resp.json()

        if "error" in data:
            return RedirectResponse(f"{frontend_url}/settings?stripe_connect_error={data['error']}")

        access_token: str = data.get("access_token", "")
        refresh_token: str = data.get("refresh_token", "")
        stripe_account_id: str = data.get("stripe_user_id", "")
        livemode: bool = data.get("livemode", False)
        scope: str = data.get("scope", "read_only")

        # Best-effort: fetch the connected account email
        stripe_email = ""
        try:
            acct = stripe.Account.retrieve(
                stripe_account_id,
                api_key=settings.STRIPE_SECRET_KEY,
                stripe_account=None,
            )
            stripe_email = acct.get("email", "")
        except Exception:
            pass

        store.upsert_stripe_connection(
            user_id,
            {
                "stripe_account_id": stripe_account_id,
                "stripe_email": stripe_email,
                "access_token_enc": encrypt_token(access_token),
                "refresh_token_enc": encrypt_token(refresh_token) if refresh_token else None,
                "token_scope": scope,
                "livemode": livemode,
                "connected": True,
                "last_error": None,
            },
        )

        log_action(
            user_id=user_id,
            agent_type="billing",
            action=f"Connected Stripe account: {stripe_email or stripe_account_id}",
            output={"account_id": stripe_account_id, "scope": scope},
            triggered_by="user",
        )

        return RedirectResponse(f"{frontend_url}/settings?stripe_connect_success=true")

    except Exception as exc:
        print(f"[stripe-connect] callback error: {exc}")
        return RedirectResponse(f"{frontend_url}/settings?stripe_connect_error=token_exchange_failed")


@router.get("/status")
async def stripe_connect_status(user=Depends(get_current_user)):
    """Return connection status for the settings page."""
    conn = store.get_stripe_connection(user.id)
    if not conn:
        return {"connected": False}
    return {
        "connected": True,
        "email": conn.get("stripe_email"),
        "account_id": conn.get("stripe_account_id"),
        "last_sync": conn.get("last_sync_at"),
        "last_sync_count": conn.get("last_sync_txn_count", 0),
        "livemode": conn.get("livemode", False),
    }


@router.post("/sync")
async def trigger_sync(user=Depends(get_current_user)):
    """Manually pull transactions from the connected Stripe account."""
    from app.services.stripe_sync import sync_stripe_transactions

    result = await sync_stripe_transactions(user.id)
    if "error" in result and not result.get("synced_count"):
        raise HTTPException(400, result["error"])
    return result


@router.delete("/disconnect")
async def disconnect_stripe(user=Depends(get_current_user)):
    """Revoke the OAuth connection and remove local record."""
    conn = store.get_stripe_connection(user.id)
    if not conn:
        return {"disconnected": True}

    # Revoke on Stripe's side (best-effort)
    if settings.STRIPE_CONNECT_CLIENT_ID:
        try:
            stripe.OAuth.deauthorize(
                client_id=settings.STRIPE_CONNECT_CLIENT_ID,
                stripe_user_id=conn["stripe_account_id"],
                api_key=settings.STRIPE_SECRET_KEY,
            )
        except Exception:
            pass

    store.delete_stripe_connection(user.id)

    log_action(
        user_id=user.id,
        agent_type="billing",
        action="Disconnected Stripe account",
        output={"account_id": conn.get("stripe_account_id")},
        triggered_by="user",
    )

    return {"disconnected": True}
