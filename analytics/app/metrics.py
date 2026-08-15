"""Turn the product's tables into the numbers the dashboard shows.

Everything here is a read. The service holds a service-role key because it
reports ACROSS tenants — which row-level security exists to prevent for ordinary
keys — so it takes no user input that could reach a query, and exposes no write
path at all.

Two joins deserve naming, because both have already caused a bug in this
codebase:

  * `auth.users` and `public.users` are joined **by id, never by email**. The
    demo tenant's profile email was repointed once already; its auth email is
    still demo@kora.app while its profile row reads pandasivananda0@gmail.com.
    An email join would have silently split one person into two rows.
  * "Signed in" comes from `auth.users.last_sign_in_at`, not from any activity
    table. Seeded rows carry a user_id without anyone ever having logged in, and
    conflating the two would credit the product with visitors it never had.
"""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from supabase import create_client

from . import config

# Tables counted per tenant. Each is a thing a person made or an agent did, so a
# tenant with rows here did something beyond registering.
ACTIVITY_TABLES = ("agent_logs", "transactions", "invoices", "contracts")

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _client():
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)


def mask_email(email: str) -> str:
    """kt••••00@gmail.com — recognisable, not deliverable.

    Keeps the first two and last two characters of the local part. A single
    leading initial is not enough: two of the real testers are `kteja4000` and
    `krishnateja.thallapalli`, which collapse to the identical `k••••••@gmail.com`
    and make two people look like one row. Distinguishing accounts is the entire
    job of this table, so the mask has to preserve it.

    Local parts of three characters or fewer keep only the first character —
    there is nothing left to hide otherwise.
    """
    if not email or "@" not in email:
        return "—"
    local, _, domain = email.partition("@")
    # A one-character local cannot be partially hidden — keeping "the first
    # character" IS the whole address — so drop it entirely.
    if len(local) <= 1:
        return f"•••@{domain}"
    if len(local) <= 3:
        return f"{local[0]}••@{domain}"
    # Keep the window narrower on short locals. Two-and-two on a four-character
    # name spells the whole thing back out — `demo` masks to `de••mo`, which
    # hides nothing at all.
    head_n, tail_n = (1, 1) if len(local) <= 5 else (2, 2)
    head, tail = local[:head_n], local[-tail_n:]
    hidden = len(local) - head_n - tail_n
    return f"{head}{'•' * max(2, min(hidden, 6))}{tail}@{domain}"


def _display_email(email: str) -> str:
    return email if config.SHOW_EMAILS else mask_email(email)


def _iso_day(value: str | None) -> str | None:
    return value[:10] if value else None


def _parse(value) -> datetime | None:
    """Accept the several shapes Supabase returns for a timestamp column."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _last_sign_ins(sb) -> dict[str, str | None]:
    """user id → last sign-in timestamp, straight from Supabase auth.

    Returns an empty map rather than raising if the admin API is unavailable:
    a dashboard that loses one column is far better than one that shows nothing.
    """
    try:
        users = sb.auth.admin.list_users()
    except Exception as exc:  # pragma: no cover - depends on live auth service
        print(f"[analytics] could not read auth users ({type(exc).__name__}: {str(exc)[:120]})")
        return {}
    out: dict[str, str | None] = {}
    for user in users or []:
        stamp = _parse(getattr(user, "last_sign_in_at", None))
        out[str(getattr(user, "id", ""))] = stamp.isoformat() if stamp else None
    return out


def _rows(sb, table: str, columns: str) -> list[dict]:
    try:
        return sb.table(table).select(columns).execute().data or []
    except Exception as exc:  # pragma: no cover - a table may lag a migration
        print(f"[analytics] {table}: skipped ({type(exc).__name__}: {str(exc)[:100]})")
        return []


def build_snapshot() -> dict:
    sb = _client()
    now = datetime.now(timezone.utc)

    users = _rows(sb, "users", "id,email,created_at,plan,onboarding_completed")
    sign_ins = _last_sign_ins(sb)
    agent_logs = _rows(sb, "agent_logs", "user_id,agent_type,triggered_by,status,created_at")

    per_tenant: dict[str, Counter] = defaultdict(Counter)
    for table in ACTIVITY_TABLES:
        for row in _rows(sb, table, "user_id"):
            uid = row.get("user_id")
            if uid:
                per_tenant[uid][table] += 1

    # ── People ──────────────────────────────────────────────────────────────
    people: list[dict] = []
    for row in users:
        uid = row.get("id") or ""
        email = (row.get("email") or "").lower()
        counts = per_tenant.get(uid, Counter())
        last_seen = sign_ins.get(uid)
        parsed_seen = _parse(last_seen)
        people.append(
            {
                "id": uid,
                "email": _display_email(email),
                "isTest": email in config.TEST_ACCOUNTS,
                "plan": row.get("plan") or "free",
                "onboarded": bool(row.get("onboarding_completed")),
                "signedUp": row.get("created_at"),
                "lastSignIn": last_seen,
                "hasSignedIn": bool(last_seen),
                "activeLast7d": bool(parsed_seen and (now - parsed_seen) <= timedelta(days=7)),
                "agentRuns": counts.get("agent_logs", 0),
                "transactions": counts.get("transactions", 0),
                "invoices": counts.get("invoices", 0),
                "contracts": counts.get("contracts", 0),
            }
        )
    people.sort(key=lambda p: (p["isTest"], -(p["agentRuns"]), p["signedUp"] or ""))

    external = [p for p in people if not p["isTest"]]
    internal = [p for p in people if p["isTest"]]

    def totals(group: list[dict]) -> dict:
        return {
            "people": len(group),
            "signedIn": sum(1 for p in group if p["hasSignedIn"]),
            "activeLast7d": sum(1 for p in group if p["activeLast7d"]),
            "onboarded": sum(1 for p in group if p["onboarded"]),
            "agentRuns": sum(p["agentRuns"] for p in group),
            "transactions": sum(p["transactions"] for p in group),
            "invoices": sum(p["invoices"] for p in group),
            "contracts": sum(p["contracts"] for p in group),
        }

    # ── Agent activity ──────────────────────────────────────────────────────
    by_type = Counter(r.get("agent_type") or "unknown" for r in agent_logs)
    by_trigger = Counter(r.get("triggered_by") or "unknown" for r in agent_logs)
    by_status = Counter(r.get("status") or "unknown" for r in agent_logs)

    runs_by_day = Counter(_iso_day(r.get("created_at")) for r in agent_logs)
    runs_by_day.pop(None, None)
    signups_by_day = Counter(_iso_day(u.get("created_at")) for u in users)
    signups_by_day.pop(None, None)

    daily = _dense_days(runs_by_day, signups_by_day)

    return {
        "generatedAt": now.isoformat(),
        "emailsMasked": not config.SHOW_EMAILS,
        "productUrl": config.PRODUCT_URL,
        "external": totals(external),
        "internal": totals(internal),
        "byAgentType": [{"type": t, "runs": n} for t, n in by_type.most_common()],
        "byTrigger": [{"trigger": t, "runs": n} for t, n in by_trigger.most_common()],
        "byStatus": dict(by_status),
        "daily": daily,
        "people": people,
    }


def _dense_days(runs: Counter, signups: Counter) -> list[dict]:
    """One entry per calendar day across the whole span, gaps included.

    Plotting only the days that have rows would compress quiet stretches and
    draw a busier product than the one that exists — the gaps ARE the signal on
    a usage chart, so they occupy their real width.
    """
    days = sorted(set(runs) | set(signups))
    if not days:
        return []
    start = datetime.fromisoformat(days[0])
    end = datetime.fromisoformat(days[-1])
    out = []
    cursor = start
    while cursor <= end:
        key = cursor.strftime("%Y-%m-%d")
        out.append({"date": key, "runs": runs.get(key, 0), "signups": signups.get(key, 0)})
        cursor += timedelta(days=1)
    return out


def get_snapshot(force: bool = False) -> dict:
    """Cached snapshot. A demo means refreshing the page in front of people."""
    with _lock:
        cached = _cache.get("snapshot")
        if cached and not force and (time.time() - cached[0]) < config.CACHE_TTL_SECONDS:
            return cached[1]
    snapshot = build_snapshot()
    with _lock:
        _cache["snapshot"] = (time.time(), snapshot)
    return snapshot


def clear_cache() -> None:
    with _lock:
        _cache.clear()
