from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..backends.user_data import CURRENT_CONSENT_VERSION
from ..config import settings
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
    """Backend-agnostic export of everything the user owns (GDPR Art. 20).

    `account` is the FULL `users` record — the profile JSONB (owner details,
    tax_id, business address, all six nested domains), plan/billing ids,
    google_email and consent — not just a handful of flat fields. `agent_memory`
    adds the butler/manager working memory. `tables` is every user-scoped row.
    """
    user = store.get_user(user_id)
    account = user.model_dump(by_alias=False) if user else {}
    # Keep a flat `email` at the top of `account` for convenience; it is already
    # inside the model dump. Nothing here is dropped vs. what the user owns.
    payload: dict = {
        "format_version": "1.1",
        "exported_at": _iso_now(),
        "account": account,
        "agent_memory": {
            "butler": store.get_butler_memory(user_id),
            "manager": store.get_manager_memory(user_id),
        },
        "tables": store.list_user_data(user_id),
    }
    return payload


async def _delete_payload(user: User) -> dict:
    """GDPR right-to-erasure. Reports the TRUTH about what happened.

    `deleted` is True only when the erasure of identity + data actually
    completed (or was genuinely not applicable). Best-effort steps that fail —
    Google revoke, Stripe cancel, GCS wipe — are surfaced in `warnings` rather
    than hidden behind an unconditional `deleted: true`. Steps whose failure
    means PII survives (auth identity) go into `errors` and flip `deleted`.

    Order:
      1. Revoke the Google OAuth grant at Google (BEFORE the token row is wiped).
      2. Cancel the Stripe subscription (stop billing).
      3. Delete GCS files for the user.
      4. Delete every row in USER_DATA_TABLES (+ the `users` row).
      5. Delete the Supabase auth identity (holds the login email).
      6. Append a no-PII audit row (with per-step outcomes) to `deletion_log`.
    """
    user_id = user.id
    user_request_id = str(uuid.uuid4())
    files_deleted = 0
    side_effects: dict[str, str] = {}
    warnings: list[str] = []
    errors: list[str] = []

    # 1. Google OAuth revoke — MUST run before step 4 wipes google_connections.
    # Deleting our local copy of the token does NOT invalidate it at Google;
    # only /revoke does. Skipping this leaves KORA an authorized app on the
    # user's Google account after they've "deleted" everything.
    try:
        token = store.get_google_token(user_id)
        if token:
            from ..clients.pool import get_async_http

            resp = await get_async_http().post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                timeout=5.0,
            )
            if resp.status_code < 400:
                side_effects["google_revoke"] = "revoked"
            else:
                side_effects["google_revoke"] = f"failed: http {resp.status_code}"
                warnings.append("google_token_not_revoked")
        else:
            side_effects["google_revoke"] = "not_applicable: no connected token"
    except Exception as exc:
        side_effects["google_revoke"] = f"failed: {type(exc).__name__}"
        warnings.append("google_token_not_revoked")

    # 2. Stripe subscription cancel — stop billing.
    try:
        sub_id = user.stripe_subscription_id if user else None
        if sub_id:
            import os
            import stripe

            stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
            stripe.Subscription.cancel(sub_id)
            side_effects["stripe_cancel"] = "cancelled"
        else:
            side_effects["stripe_cancel"] = "not_applicable: no subscription"
    except Exception as exc:
        side_effects["stripe_cancel"] = f"failed: {type(exc).__name__}"
        warnings.append("stripe_subscription_not_cancelled")

    # 3. GCS files
    try:
        from ..services.storage import delete_user_data as _delete_files

        files_deleted = _delete_files(user_id)
        side_effects["gcs_delete"] = f"deleted: {files_deleted}"
    except Exception as exc:
        side_effects["gcs_delete"] = f"failed: {type(exc).__name__}"
        warnings.append("stored_files_may_remain")

    # 4. Database rows (every user-scoped table + the users row)
    tables_cleared = store.delete_user_data(user_id)

    # 5. Supabase auth identity (holds the login email in auth.users). If
    # Supabase is configured and this fails, PII survives → hard error.
    from ..config import settings

    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
        try:
            from supabase import create_client

            admin = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
            admin.auth.admin.delete_user(user_id)
            side_effects["auth_delete"] = "deleted"
        except Exception as exc:
            side_effects["auth_delete"] = f"failed: {type(exc).__name__}"
            errors.append("auth_identity_not_deleted")
    else:
        # No Supabase auth backend in this environment (e.g. mock/dev): there is
        # no separate auth identity to remove, so this is genuinely N/A.
        side_effects["auth_delete"] = "not_applicable: no auth backend"

    deleted = not errors

    # 6. Audit log (no PII — status strings + counts only)
    try:
        store.record_deletion(
            reason="user_request",
            tables_cleared=tables_cleared,
            files_deleted=files_deleted,
            user_request_id=user_request_id,
            side_effects=side_effects,
        )
        side_effects["deletion_log"] = "recorded"
    except Exception as exc:
        side_effects["deletion_log"] = f"failed: {type(exc).__name__}"
        warnings.append("audit_row_not_written")

    return {
        "deleted": deleted,
        "user_request_id": user_request_id,
        "files_removed": files_deleted,
        "tables_cleared": tables_cleared,
        "side_effects": side_effects,
        "warnings": warnings,
        "errors": errors,
    }


def _is_protected_tenant(user_id: str) -> bool:
    """True when this tenant is a SHARED account that must not be erased.

    Right-to-erasure assumes the caller owns the data they are destroying. That
    assumption breaks for the published demo account: everyone signs in with the
    same credentials, so one caller's "delete my account" silently destroys the
    seeded data, revokes the owner's Google grant, and deletes the auth identity
    behind the printed login — for every later visitor, irreversibly.

    Configured via PROTECTED_TENANT_IDS and empty by default, so a real tenant's
    own deletion is never affected.
    """
    raw = settings.PROTECTED_TENANT_IDS or ""
    return bool(user_id) and user_id in {part.strip() for part in raw.split(",") if part.strip()}


@router.delete("/delete")
async def delete_account(user: User = Depends(get_current_user)):
    """Permanently delete the account and all associated data (GDPR right to erasure).

    Order: revoke Google grant → cancel Stripe → delete GCS files → delete DB
    rows → delete auth identity → append a no-PII audit row. The response's
    `deleted` flag is honest: false (with `errors`) if identity/data removal
    failed; best-effort step failures appear in `warnings`.

    Shared demo tenants are refused outright (409) rather than being given a
    fake success. Reporting `deleted: true` without deleting would be exactly
    the dishonest response `_delete_payload` was written to avoid.
    """
    if _is_protected_tenant(user.id):
        raise HTTPException(
            status_code=409,
            detail=(
                "This is a shared demo account, so erasure is disabled. The data here "
                "belongs to everyone evaluating Kora, not to one signed-in visitor, and "
                "deleting it would remove the account for every later visitor. Nothing "
                "was deleted. Data export (GET /api/account/export) works normally, and "
                "creating your own account gives you a private tenant where deletion is "
                "fully enabled."
            ),
        )
    return await _delete_payload(user)


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
    account = payload["account"]
    writer.writerow(["format_version", payload["format_version"]])
    writer.writerow(["exported_at", payload["exported_at"]])
    writer.writerow(["account.email", account.get("email") or ""])
    writer.writerow(["account.full_name", account.get("full_name") or ""])
    writer.writerow(["account.business_name", account.get("business_name") or ""])
    writer.writerow(["account.profile", _csv_cell(account.get("profile"))])
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
