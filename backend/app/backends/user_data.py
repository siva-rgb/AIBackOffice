"""M9 — single source of truth for tables that hold user-owned PII.

Exports `USER_DATA_TABLES`, the registry consulted by:
  - `app/backends/{memory_store,supabase_store}.list_user_data()`
  - `app/backends/{memory_store,supabase_store}.delete_user_data()`
  - `app/routers/account.py::export_data()`
  - `app/routers/account.py::delete_account()`

A table MUST appear here if it carries a `user_id` column with user-scoped data,
even if it has no dedicated `list_X(user_id)` function in the store layer
(those tables are accessed via raw table handles).

Order matters for deletion: FK children before parents. For Supabase `ON DELETE
CASCADE` exists on most FKs (see `docs/specs/schema.sql`), but ordering
defensively is cheaper than debugging an FK violation in production.
"""

from __future__ import annotations

# Read-mostly data (export covers, deletion covers)
USER_DATA_TABLES: tuple[str, ...] = (
    # Children first (FK order)
    "stories",
    "tasks",
    "client_notes",
    "engagements",
    "proposals",
    "retainers",
    "quick_captures",
    "client_view_cache",
    "agent_memory",
    "kg_edges",
    "kg_nodes",
    "agent_logs",
    "alerts",
    "cashflow_forecasts",
    "reports",
    "invoices",
    "contracts",
    "transactions",
    "meetings",
    "meeting_action_items",
    "drive_doc_cache",
    "email_intel_cache",
    "business_playbook",
    "manager_tasks",
    "clients",
    # Connections (parent-ish — no FK to other user tables)
    "google_connections",
    "stripe_connections",
    "notion_connections",
)

# Sensitive sub-set returned in the export payload (PII tables).
EXPORT_TABLES: tuple[str, ...] = USER_DATA_TABLES

# Current consent policy version. Bumped on every Terms/Privacy update.
# Clients hit `POST /api/account/consent` to re-consent when this changes.
CURRENT_CONSENT_VERSION: str = "2026-06-01"
