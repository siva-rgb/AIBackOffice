from __future__ import annotations

from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from ..config import settings
from .token_encryption import decrypt_token, encrypt_token


def _db():
    from supabase import create_client
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def get_user_credentials(user_id: str) -> Credentials | None:
    """Return valid Google credentials for user_id, refreshing if expired.

    Returns None when the user has not connected Google or when refresh fails.
    Sync (not async) so it can be called from both sync services and async routes.
    """
    if not settings.SUPABASE_URL:
        return None

    db = _db()
    rows = db.table("google_connections").select("*").eq(
        "user_id", user_id).eq("connected", True).execute().data
    if not rows:
        return None
    conn = rows[0]

    try:
        access_token = decrypt_token(conn["access_token_enc"])
        refresh_token = (decrypt_token(conn["refresh_token_enc"])
                         if conn.get("refresh_token_enc") else None)
    except Exception as exc:
        # Token was encrypted with a different/lost key — unrecoverable. Flag the
        # connection so the UI prompts a reconnect instead of silently doing nothing.
        db.table("google_connections").update({
            "connected": False,
            "last_error": f"Token undecryptable — reconnect required ({type(exc).__name__})",
        }).eq("user_id", user_id).execute()
        db.table("users").update({"google_connected": False}).eq("id", user_id).execute()
        return None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=conn.get("scopes_granted") or [],
    )

    if conn.get("token_expiry"):
        try:
            expiry_str = conn["token_expiry"].replace("Z", "+00:00")
            dt = datetime.fromisoformat(expiry_str)
            # google-auth compares expiry against a naive UTC now(), so expiry
            # must also be naive UTC — an aware datetime raises TypeError.
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            creds.expiry = dt
        except Exception:
            pass

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            db.table("google_connections").update({
                "access_token_enc": encrypt_token(creds.token or ""),
                "token_expiry": creds.expiry.isoformat() if creds.expiry else None,
                "last_used_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
            }).eq("user_id", user_id).execute()
        except Exception as exc:
            db.table("google_connections").update({
                "connected": False,
                "last_error": str(exc)[:500],
            }).eq("user_id", user_id).execute()
            db.table("users").update({"google_connected": False}).eq(
                "id", user_id).execute()
            return None

    return creds
