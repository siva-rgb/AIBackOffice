from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ..dependencies import get_current_user
from ..models import User
from .. import store

router = APIRouter(prefix="/api/account", tags=["account"])


@router.delete("/delete")
async def delete_account(user: User = Depends(get_current_user)):
    """
    Permanently delete the account and all associated data (GDPR right to erasure).
    Order: revoke OAuth → cancel Stripe → delete GCS files → delete DB rows → delete auth user.
    """
    from ..config import settings
    from supabase import create_client

    user_id = user.id
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    # 1. Revoke Google OAuth token
    try:
        rows = db.table("google_connections").select("access_token_enc").eq("user_id", user_id).execute().data
        if rows and rows[0].get("access_token_enc"):
            from ..services.token_encryption import decrypt_token
            import httpx

            token = decrypt_token(rows[0]["access_token_enc"])
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": token},
                    timeout=5.0,
                )
    except Exception:
        pass

    # 2. Cancel Stripe subscription
    try:
        user_data = store.get_user(user_id)
        stripe_sub_id = user_data.stripe_subscription_id if user_data else None
        if stripe_sub_id:
            import stripe
            import os

            stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
            stripe.Subscription.cancel(stripe_sub_id)
    except Exception:
        pass

    # 3. Delete GCS files
    files_deleted = 0
    try:
        from ..services.storage import delete_user_data

        files_deleted = delete_user_data(user_id)
    except Exception:
        pass

    # 4. Delete DB records (in dependency order)
    tables = [
        "business_playbook",
        "email_intel_cache",
        "drive_doc_cache",
        "meeting_action_items",
        "meetings",
        "client_notes",
        "quick_captures",
        "manager_tasks",
        "agent_logs",
        "alerts",
        "cashflow_forecasts",
        "engagements",
        "proposals",
        "retainers",
        "google_connections",
        "invoices",
        "contracts",
        "transactions",
        "reports",
        "clients",
    ]
    for table in tables:
        try:
            db.table(table).delete().eq("user_id", user_id).execute()
        except Exception:
            pass

    # 5. Delete user profile row
    try:
        db.table("users").delete().eq("id", user_id).execute()
    except Exception:
        pass

    # 6. Delete Supabase auth identity
    try:
        db.auth.admin.delete_user(user_id)
    except Exception:
        pass

    # 7. Audit log — no PII, just a timestamp
    try:
        db.table("deletion_log").insert(
            {
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "files_deleted": files_deleted,
                "reason": "user_request",
            }
        ).execute()
    except Exception:
        pass

    return {"deleted": True, "files_removed": files_deleted}


@router.get("/export")
async def export_data(user: User = Depends(get_current_user)):
    """Export all user data as JSON (GDPR right to data portability)."""
    from ..config import settings
    from supabase import create_client

    user_id = user.id
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    export: dict = {}

    # Profile (strip sensitive internal fields)
    user_data = store.get_user(user_id)
    if user_data:
        export["profile"] = {
            "email": user_data.email,
            "full_name": user_data.full_name,
            "business_name": (user_data.profile or {}).get("business_name"),
            "country": (user_data.profile or {}).get("country"),
            "timezone": (user_data.profile or {}).get("timezone"),
            "currency": (user_data.profile or {}).get("currency"),
        }

    def _rows(table: str) -> list:
        try:
            return db.table(table).select("*").eq("user_id", user_id).execute().data or []
        except Exception:
            return []

    export["clients"] = _rows("clients")
    export["invoices"] = _rows("invoices")
    export["contracts"] = _rows("contracts")
    export["transactions"] = _rows("transactions")
    export["engagements"] = _rows("engagements")
    export["proposals"] = _rows("proposals")
    export["retainers"] = _rows("retainers")
    export["meetings"] = _rows("meetings")
    export["quick_captures"] = _rows("quick_captures")
    export["playbook"] = _rows("business_playbook")
    export["agent_logs_count"] = len(_rows("agent_logs"))

    export["exported_at"] = datetime.now(timezone.utc).isoformat()
    export["format_version"] = "1.0"

    return export
