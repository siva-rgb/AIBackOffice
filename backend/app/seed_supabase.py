"""Seed the Supabase project with a demo business.

Creates (or reuses) an auth user — required because public.users.id is a FK to
auth.users — then loads the demo dataset under that user's UUID. Idempotent:
clears the user's rows before re-seeding.

Run (defaults to demo@kora.app):
    python -m app.seed_supabase
Seed a custom user:
    python -m app.seed_supabase <email> <password> ["Full Name"] ["Business Name"]
"""

from __future__ import annotations

import sys

from .backends import supabase_store as sbs
from .seed import build_seed

sb = sbs._sb

DEMO_EMAIL = "demo@kora.app"
DEMO_PASSWORD = "Kora-Demo-2026!"
# Order matters for FK deletes — children before parents.
_CHILD_TABLES = [
    "agent_logs",
    "alerts",
    "invoices",
    # Butler tables (delete before contracts/clients they reference)
    "client_notes",
    "engagements",
    "proposals",
    "retainers",
    "quick_captures",
    "clients",
    "contracts",
    "transactions",
    "reports",
    "cashflow_forecasts",
]


def get_or_create_user(email: str, password: str, full_name: str) -> str:
    try:
        users = sb.auth.admin.list_users()
        for u in users:
            if getattr(u, "email", None) == email:
                return u.id
    except Exception as exc:  # pragma: no cover
        print("  (list_users failed, will try create):", str(exc)[:120])

    res = sb.auth.admin.create_user(
        {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": full_name},
        }
    )
    return res.user.id


def seed_business(email: str, password: str, full_name: str, business_name: str) -> str:
    uid = get_or_create_user(email, password, full_name)
    print(f"  auth user: {uid}")

    for t in _CHILD_TABLES:
        try:
            sb.table(t).delete().eq("user_id", uid).execute()
        except Exception as exc:
            print(f"  clear {t}: {str(exc)[:80]}")

    sb.table("users").upsert(
        {
            "id": uid,
            "email": email,
            "full_name": full_name,
            "business_name": business_name,
            "country": "US",
            "currency": "USD",
            "plan": "pro",
            "onboarding_completed": True,
        }
    ).execute()

    data = build_seed(uid)
    ins = sbs.insert_transactions(data["transactions"])
    # Contracts before invoices: an invoice may carry a contract_id FK.
    for c in data["contracts"]:
        sbs.insert_contract(c)
    for inv in data["invoices"]:
        sbs.insert_invoice(inv)
    for log in data["agent_logs"]:
        sbs.insert_agent_log(log)
    for a in data["alerts"]:
        sbs.insert_alert(a)

    # Butler demo data (requires migrations/2026-06-02_add_butler.sql). Insert in
    # FK order: clients → engagements (ref contracts) → notes → proposals → retainers.
    butler_counts = _seed_butler(data)

    print(
        f"  inserted: {len(ins)} transactions, {len(data['invoices'])} invoices, "
        f"{len(data['contracts'])} contracts, {len(data['agent_logs'])} agent logs, "
        f"{len(data['alerts'])} alerts"
    )
    if butler_counts:
        print(
            f"  butler:   {butler_counts['clients']} clients, {butler_counts['engagements']} engagements, "
            f"{butler_counts['notes']} notes, {butler_counts['proposals']} proposals, "
            f"{butler_counts['retainers']} retainers"
        )
    return uid


def _seed_butler(data: dict) -> dict | None:
    """Insert Butler demo records. Best-effort: if the Butler tables don't exist
    yet (migration not applied), skip with a clear note instead of failing the seed."""
    try:
        for c in data.get("clients", []):
            sbs.insert_client(c)
        for e in data.get("engagements", []):
            sbs.insert_engagement(e)
        for n in data.get("client_notes", []):
            sbs.insert_client_note(n)
        for p in data.get("proposals", []):
            sbs.insert_proposal(p)
        for r in data.get("retainers", []):
            sbs.insert_retainer(r)
    except Exception as exc:
        print("  butler:   SKIPPED: apply migrations/2026-06-02_add_butler.sql first " f"({str(exc)[:100]})")
        return None
    return {
        "clients": len(data.get("clients", [])),
        "engagements": len(data.get("engagements", [])),
        "notes": len(data.get("client_notes", [])),
        "proposals": len(data.get("proposals", [])),
        "retainers": len(data.get("retainers", [])),
    }


def main() -> None:
    args = sys.argv[1:]
    if args:
        email = args[0]
        password = args[1] if len(args) > 1 else "Test-1234!"
        full_name = args[2] if len(args) > 2 else email.split("@")[0].title()
        business_name = args[3] if len(args) > 3 else f"{full_name} Studio"
    else:
        email, password, full_name, business_name = (DEMO_EMAIL, DEMO_PASSWORD, "Alex Rivera", "Rivera Studio")

    print(f"Seeding Supabase business for {email} ...")
    seed_business(email, password, full_name, business_name)
    print(f"\nDone. Login: {email} / {password}")


if __name__ == "__main__":
    main()
