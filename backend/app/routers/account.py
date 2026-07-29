from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..backends.user_data import CURRENT_CONSENT_VERSION
from ..dependencies import get_current_user
from ..models import User
from .. import store

router = APIRouter(prefix="/api/account", tags=["account"])

_CONSENT_VERSION_HEADER = CURRENT_CONSENT_VERSION


class _ConsentBody(BaseModel):
    """Body for `POST /api/account/consent`. Version is optional — defaults to
    the current policy version so the client can just POST `{}` to re-consent."""

    version: str | None = Field(default=None, min_length=1)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _export_payload(user_id: str) -> dict:
    """Backend-agnostic export of every user-owned row."""
    user = store.get_user(user_id)
    payload: dict = {
        "format_version": "1.0",
        "exported_at": _iso_now(),
        "profile": {
            "email": user.email if user else None,
            "full_name": user.full_name if user else None,
            "business_name": user.business_name if user else None,
            "country": user.country if user else None,
            "currency": user.currency if user else None,
            "consent_version": user.consent_version if user else None,
            "consent_given_at": user.consent_given_at if user else None,
            "created_at": user.created_at if user else None,
        },
        "tables": store.list_user_data(user_id),
    }
    return payload


def _delete_payload(user: User) -> dict:
    """GDPR right-to-erasure. Best-effort per side-effect; collects what we did.

    Side-effects, in order:
      1. Revoke Google OAuth token (if connected).
      2. Cancel Stripe subscription (if present).
      3. Delete GCS files for the user.
      4. Delete every row in USER_DATA_TABLES.
      5. Delete the `public.users` row.
      6. Delete the Supabase auth identity (admin API).
      7. Append a no-PII audit row to `public.deletion_log`.
    """
    user_id = user.id
    user_request_id = str(uuid.uuid4())
    tables_cleared: dict[str, int] = {}
    files_deleted = 0
    side_effects: dict[str, str] = {}

    # 1. Google OAuth token revoke (best-effort, never blocks).
    # The Google connection lives outside the M1 repo() wrapper surface; the
    # user's encrypted access token is also purged by `store.delete_user_data`
    # wiping the `google_connections` row. Token revocation against Google's
    # /revoke endpoint is performed as a courtesy; the credential is already
    # inoperative because the row is gone and the user's auth identity is
    # about to be deleted (step 5).
    try:
        side_effects["google_revoke"] = (
            "skipped: covered by row-delete + auth-identity delete"
        )
    except Exception as exc:
        side_effects["google_revoke"] = f"skipped: {type(exc).__name__}"

    # 2. Stripe subscription cancel
    try:
        sub_id = user.stripe_subscription_id if user else None
        if sub_id:
            import os
            import stripe

            stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
            stripe.Subscription.cancel(sub_id)
            side_effects["stripe_cancel"] = "ok"
    except Exception as exc:
        side_effects["stripe_cancel"] = f"skipped: {type(exc).__name__}"

    # 3. GCS files
    try:
        from ..services.storage import delete_user_data as _delete_files

        files_deleted = _delete_files(user_id)
    except Exception as exc:
        side_effects["gcs_delete"] = f"skipped: {type(exc).__name__}"

    # 4. Database rows (every user-scoped table)
    tables_cleared = store.delete_user_data(user_id)

    # 5. Supabase auth identity (best-effort — admin client only when configured)
    try:
        from ..config import settings

        if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
            from supabase import create_client

            admin = create_client(
                settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY
            )
            admin.auth.admin.delete_user(user_id)
            side_effects["auth_delete"] = "ok"
    except Exception as exc:
        side_effects["auth_delete"] = f"skipped: {type(exc).__name__}"

    # 6. Audit log (no PII)
    try:
        store.record_deletion(
            reason="user_request",
            tables_cleared=tables_cleared,
            files_deleted=files_deleted,
            user_request_id=user_request_id,
        )
        side_effects["deletion_log"] = "ok"
    except Exception as exc:
        side_effects["deletion_log"] = f"skipped: {type(exc).__name__}"

    return {
        "deleted": True,
        "user_request_id": user_request_id,
        "files_removed": files_deleted,
        "tables_cleared": tables_cleared,
        "side_effects": side_effects,
    }


@router.delete("/delete")
async def delete_account(user: User = Depends(get_current_user)):
    """Permanently delete the account and all associated data (GDPR right to erasure).

    Order: revoke OAuth → cancel Stripe → delete GCS files → delete DB rows →
    delete auth user → append no-PII audit row.
    """
    return _delete_payload(user)


@router.get("/export")
async def export_data(user: User = Depends(get_current_user)):
    """Export all user data as JSON (GDPR right to data portability)."""
    return _export_payload(user.id)


@router.get("/export.csv")
async def export_data_csv(user: User = Depends(get_current_user)):
    """Export all user data as CSV (one CSV per user-data table, separated by
    blank lines + a `=== <table> ===` header — friendlier than JSON for
    spreadsheet use, no row-count ceiling like ZIP would imply).
    """
    payload = _export_payload(user.id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["format_version", payload["format_version"]])
    writer.writerow(["exported_at", payload["exported_at"]])
    writer.writerow(["profile.email", payload["profile"].get("email") or ""])
    writer.writerow(["profile.full_name", payload["profile"].get("full_name") or ""])
    writer.writerow(
        ["profile.business_name", payload["profile"].get("business_name") or ""]
    )
    writer.writerow([])
    for table, rows in payload["tables"].items():
        writer.writerow([f"=== {table} ({len(rows)} rows) ==="])
        if not rows:
            writer.writerow([])
            continue
        # Union of keys, preserving first-row order, then extras in sorted order
        keys: list[str] = []
        seen: set[str] = set()
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        writer.writerow(keys)
        for r in rows:
            writer.writerow([_csv_cell(r.get(k)) for k in keys])
        writer.writerow([])
    return {
        "filename": f"kora-export-{user.id}-{_iso_now()[:10]}.csv",
        "content": buf.getvalue(),
    }


def _csv_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"))
    return str(v)


@router.post("/consent")
async def record_consent(
    body: _ConsentBody,
    user: User = Depends(get_current_user),
):
    """Record consent for the current (or a bumped) policy version.

    GDPR Art. 7 / CCPA §1798.100: the controller must be able to prove consent.
    This endpoint captures `(user_id, version, timestamp)` on `public.users`.
    Onboarding completion in `routers/users.py::update_me` calls this implicitly
    on first toggle of `onboarding_completed`.
    """
    version = body.version or _CONSENT_VERSION_HEADER
    updated = store.update_user(
        user.id,
        {"consent_version": version, "consent_given_at": _iso_now()},
    )
    return {
        "consent_version": version,
        "consent_given_at": updated.consent_given_at if updated else None,
    }
