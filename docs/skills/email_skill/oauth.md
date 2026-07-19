# Google Butler — OAuth Reference

Google OAuth 2.0 with offline access. Uses the SAME GCP project as Vertex AI.
Prerequisites: Gmail API, Calendar API, Drive API, and Docs API all enabled.

---

## OAuth router (FastAPI)

```python
# backend/app/routers/auth_google.py
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from app.dependencies import get_current_user
from app.services.token_encryption import encrypt_token
from app.config import settings
from supabase import create_client
from datetime import datetime

router = APIRouter(prefix="/auth/google", tags=["google-auth"])

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]

def _build_flow(state: str = None) -> Flow:
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
        scopes=SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
        state=state,
    )


@router.get("/connect")
async def connect_google(user=Depends(get_current_user)):
    flow = _build_flow(state=user["id"])
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return {"auth_url": auth_url}


@router.get("/callback")
async def google_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    scope: str = None,
):
    frontend_url = settings.NEXT_PUBLIC_APP_URL

    if error:
        return RedirectResponse(f"{frontend_url}/settings?google_error={error}")

    if not code or not state:
        return RedirectResponse(f"{frontend_url}/settings?google_error=missing_params")

    user_id = state

    try:
        flow = _build_flow(state=state)
        flow.fetch_token(code=code)
        credentials = flow.credentials

        from googleapiclient.discovery import build as google_build
        user_info_service = google_build("oauth2", "v2", credentials=credentials)
        google_user = user_info_service.userinfo().get().execute()
        google_email = google_user.get("email", "")

        granted_scopes = scope.split(" ") if scope else list(credentials.scopes or [])

        access_enc = encrypt_token(credentials.token or "")
        refresh_enc = encrypt_token(credentials.refresh_token or "") \
                      if credentials.refresh_token else None

        db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

        db.table("google_connections").upsert({
            "user_id": user_id,
            "access_token_enc": access_enc,
            "refresh_token_enc": refresh_enc,
            "google_email": google_email,
            "scopes_granted": granted_scopes,
            "token_expiry": credentials.expiry.isoformat() if credentials.expiry else None,
            "connected": True,
            "consent_given_at": datetime.utcnow().isoformat(),
            "consent_version": "2026-06-01",
            "last_error": None,
            "updated_at": datetime.utcnow().isoformat(),
        }, on_conflict="user_id").execute()

        db.table("users").update({
            "google_connected": True,
            "google_email": google_email,
        }).eq("id", user_id).execute()

        return RedirectResponse(f"{frontend_url}/settings?google_connected=true")

    except Exception as e:
        print(f"Google OAuth callback error: {e}")
        return RedirectResponse(f"{frontend_url}/settings?google_error=token_exchange_failed")


@router.get("/status")
async def google_status(user=Depends(get_current_user)):
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    conn = db.table("google_connections").select(
        "google_email, scopes_granted, connected, last_used_at"
    ).eq("user_id", user["id"]).execute().data
    if conn and conn[0].get("connected"):
        return {
            "connected": True,
            "email": conn[0]["google_email"],
            "scopes": conn[0].get("scopes_granted", []),
            "last_sync": conn[0].get("last_used_at"),
        }
    return {"connected": False}


@router.delete("/disconnect")
async def disconnect_google(user=Depends(get_current_user)):
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    conn = db.table("google_connections").select(
        "access_token_enc"
    ).eq("user_id", user["id"]).execute().data

    if conn and conn[0].get("access_token_enc"):
        from app.services.token_encryption import decrypt_token
        import httpx
        try:
            token = decrypt_token(conn[0]["access_token_enc"])
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": token}, timeout=5.0
                )
        except Exception:
            pass

    db.table("google_connections").delete().eq("user_id", user["id"]).execute()
    db.table("users").update({
        "google_connected": False,
        "google_email": None,
    }).eq("id", user["id"]).execute()

    return {"disconnected": True}
```

---

## Token encryption

```python
# backend/app/services/token_encryption.py
import os
from cryptography.fernet import Fernet

def _get_fernet() -> Fernet:
    key = os.environ["TOKEN_ENCRYPTION_KEY"]
    return Fernet(key.encode())

def encrypt_token(token: str) -> str:
    if not token:
        return ""
    return _get_fernet().encrypt(token.encode()).decode()

def decrypt_token(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
```

---

## Credential helper with auto-refresh

```python
# backend/app/services/google_auth.py
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from app.services.token_encryption import decrypt_token, encrypt_token
from supabase import create_client
from app.config import settings
from datetime import datetime

async def get_user_credentials(user_id: str) -> Credentials | None:
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    conn = db.table("google_connections").select("*").eq(
        "user_id", user_id).eq("connected", True).execute().data

    if not conn:
        return None
    conn = conn[0]

    access_token = decrypt_token(conn["access_token_enc"])
    refresh_token = decrypt_token(conn["refresh_token_enc"]) if conn.get("refresh_token_enc") else None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=conn.get("scopes_granted", []),
    )

    if conn.get("token_expiry"):
        creds.expiry = datetime.fromisoformat(conn["token_expiry"].replace("Z", "+00:00"))

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            db.table("google_connections").update({
                "access_token_enc": encrypt_token(creds.token),
                "token_expiry": creds.expiry.isoformat() if creds.expiry else None,
                "last_used_at": datetime.utcnow().isoformat(),
                "last_error": None,
            }).eq("user_id", user_id).execute()
        except Exception as e:
            db.table("google_connections").update({
                "connected": False,
                "last_error": str(e)
            }).eq("user_id", user_id).execute()
            db.table("users").update({"google_connected": False}).eq("id", user_id).execute()
            return None

    return creds
```

---

## Next.js callback proxy

```typescript
// frontend/app/api/auth/google/callback/route.ts
import { NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  const queryString = request.nextUrl.searchParams.toString()
  const apiUrl = `${process.env.NEXT_PUBLIC_API_URL}/auth/google/callback?${queryString}`
  const response = await fetch(apiUrl, { redirect: "manual" })
  const location = response.headers.get("location")
  if (location) return NextResponse.redirect(location)
  return NextResponse.json({ error: "callback_failed" }, { status: 500 })
}
```

---

## Privacy consent UI (show before OAuth redirect)

```
Before connecting Google, here's exactly what Kora will access:

Gmail:
✓ Email threads with your clients (matched by their email addresses)
✗ Personal emails, newsletters, subscriptions — never read

Google Calendar:
✓ Your upcoming meetings and who you're meeting
✗ Event descriptions with personal details — not read unless client-related

Google Drive:
✓ Files in your "Kora" folder (you control what goes here)
✓ Google Meet transcripts (automatically saved after meetings)
✗ Your entire Drive — never browsed broadly

Your email and document content is processed by Google Gemini AI for analysis.
You can disconnect Google at any time from Settings.
```
