from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from ..config import settings
from ..dependencies import get_current_user
from ..models import User
from ..services.oauth_state import issue_oauth_state, verify_oauth_state
from ..services.token_encryption import decrypt_token, encrypt_token
from ..clients.pool import get_async_http

# oauthlib (via google-auth-oauthlib) rejects non-HTTPS OAuth and raises on the
# harmless scope reordering Google performs. Relax both for local dev — insecure
# transport is only permitted when the redirect is plain http (localhost), so a
# real https deployment keeps the strict check.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
if (settings.GOOGLE_OAUTH_REDIRECT_URI or "").startswith("http://"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

router = APIRouter(prefix="/api/auth/google", tags=["google-auth"])

_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _build_flow(state: str | None = None):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
            }
        },
        scopes=_SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
        state=state,
        # Disable PKCE: connect and callback are separate requests with separate
        # Flow objects, so an auto-generated code_verifier can't survive between
        # them ("Missing code verifier"). This is a confidential client (has a
        # secret), so PKCE is optional.
        autogenerate_code_verifier=False,
    )


def _db():
    from supabase import create_client

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


@router.get("/connect")
async def connect_google(user: User = Depends(get_current_user)):
    """Return a Google OAuth URL for the user to authorize Kora."""
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        return {"error": "Google OAuth not configured (GOOGLE_OAUTH_CLIENT_ID missing)"}
    flow = _build_flow(state=issue_oauth_state(user.id))
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return {"auth_url": auth_url}


@router.get("/callback")
async def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    scope: str | None = None,
):
    """OAuth callback — exchanges code for tokens and stores them encrypted."""
    frontend_url = settings.NEXT_PUBLIC_APP_URL

    if error:
        return RedirectResponse(f"{frontend_url}/settings?google_error={error}")
    if not code or not state:
        return RedirectResponse(f"{frontend_url}/settings?google_error=missing_params")

    user_id = verify_oauth_state(state)
    if not user_id:
        return RedirectResponse(f"{frontend_url}/settings?google_error=invalid_state")
    try:
        flow = _build_flow(state=state)
        flow.fetch_token(code=code)
        credentials = flow.credentials

        from googleapiclient.discovery import build as google_build

        ui_svc = google_build("oauth2", "v2", credentials=credentials)
        google_user = ui_svc.userinfo().get().execute()
        google_email = google_user.get("email", "")

        granted_scopes = scope.split(" ") if scope else list(credentials.scopes or [])
        now = datetime.now(timezone.utc).isoformat()

        access_enc = encrypt_token(credentials.token or "")
        refresh_enc = encrypt_token(credentials.refresh_token) if credentials.refresh_token else None

        db = _db()
        db.table("google_connections").upsert(
            {
                "user_id": user_id,
                "access_token_enc": access_enc,
                "refresh_token_enc": refresh_enc,
                "google_email": google_email,
                "scopes_granted": granted_scopes,
                "token_expiry": credentials.expiry.isoformat() if credentials.expiry else None,
                "connected": True,
                "consent_given_at": now,
                "consent_version": "2026-06-01",
                "last_error": None,
                "updated_at": now,
            },
            on_conflict="user_id",
        ).execute()

        db.table("users").update(
            {
                "google_connected": True,
                "google_email": google_email,
            }
        ).eq("id", user_id).execute()

        return RedirectResponse(f"{frontend_url}/settings?google_connected=true")

    except Exception as exc:
        print(f"[google-oauth] callback error: {exc}")
        return RedirectResponse(f"{frontend_url}/settings?google_error=token_exchange_failed")


@router.get("/status")
async def google_status(user: User = Depends(get_current_user)):
    """Return current Google connection status for the user."""
    if not settings.SUPABASE_URL:
        return {"connected": False}
    db = _db()
    rows = db.table("google_connections").select("google_email, scopes_granted, connected, last_used_at").eq("user_id", user.id).execute().data
    if rows and rows[0].get("connected"):
        return {
            "connected": True,
            "email": rows[0]["google_email"],
            "scopes": rows[0].get("scopes_granted") or [],
            "last_sync": rows[0].get("last_used_at"),
        }
    return {"connected": False}


@router.delete("/disconnect")
async def disconnect_google(user: User = Depends(get_current_user)):
    """Revoke Google token and clear connection record."""
    if not settings.SUPABASE_URL:
        return {"disconnected": True}
    db = _db()
    rows = db.table("google_connections").select("access_token_enc").eq("user_id", user.id).execute().data

    if rows and rows[0].get("access_token_enc"):
        try:
            token = decrypt_token(rows[0]["access_token_enc"])
            client = get_async_http()
            await client.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                timeout=5.0,
            )
        except Exception:
            pass

    db.table("google_connections").delete().eq("user_id", user.id).execute()

    # Clear all cached Google data — required by Google's Limited Use policy.
    for cache_table in ("email_intel_cache", "drive_doc_cache"):
        try:
            db.table(cache_table).delete().eq("user_id", user.id).execute()
        except Exception:
            pass

    db.table("users").update(
        {
            "google_connected": False,
            "google_email": None,
        }
    ).eq("id", user.id).execute()

    return {"disconnected": True}
