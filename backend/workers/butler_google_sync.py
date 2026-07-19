"""
Butler Google sync worker.

Cloud Scheduler target: 0 7 * * * (07:00 UTC daily)
Run locally: python -m workers.butler_google_sync

Sync order per user:
  1. Gmail intel (email threads per active client)
  2. Drive intel (Kora folder + Meet transcripts)
  3. Calendar intel is fetched live in gather state — no sync needed here
  4. Butler morning briefing (uses the enriched state)
"""
from __future__ import annotations

import sys
import os

# Allow running as a script from the backend root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.services.gmail_intel import sync_client_email_intel
from app.services.drive_intel import sync_drive_intel
from app.services import butler


def run_for_user(user_id: str) -> dict:
    if not settings.SUPABASE_URL:
        return {"skipped": True, "reason": "supabase not configured"}

    from supabase import create_client
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    conn_rows = db.table("google_connections").select("connected").eq(
        "user_id", user_id).execute().data
    if conn_rows and conn_rows[0].get("connected"):
        print(f"[sync] Gmail intel for {user_id}")
        sync_client_email_intel(user_id)
        print(f"[sync] Drive intel for {user_id}")
        sync_drive_intel(user_id)

    print(f"[sync] Morning briefing for {user_id}")
    return butler.generate_morning_briefing(user_id, triggered_by="scheduler")


def run() -> None:
    if not settings.SUPABASE_URL:
        print("[sync] Supabase not configured — skipping")
        return
    from supabase import create_client
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    users = db.table("users").select("id").execute().data
    for row in users:
        try:
            result = run_for_user(row["id"])
            print(f"[sync] {row['id']}: {result.get('briefing', {}).get('headline', 'done')}")
        except Exception as exc:
            print(f"[sync] failed for {row['id']}: {exc}")


if __name__ == "__main__":
    run()
