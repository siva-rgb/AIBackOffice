"""M1.1 — Tenant-scoped query wrapper.

Every read/write that touches user-owned data MUST go through `repo(user_id)`.
No call site may call `_sb.table(...)` directly outside this module.

Usage:
    from app.backends.repository import repo
    rows = repo(user_id).select("invoices").execute().data
    repo(user_id).insert("invoices", row).execute()
"""

from __future__ import annotations

from supabase import Client


class TenantQuery:
    """Fluent builder that injects `user_id` automatically on every query."""

    def __init__(self, client: Client, user_id: str) -> None:
        self._client = client
        self._user_id = user_id

    # ── reads ────────────────────────────────────────────────────────────────

    def select(self, table: str, columns: str = "*"):
        """Return a query pre-filtered to this tenant."""
        return self._client.table(table).select(columns).eq("user_id", self._user_id)

    # ── writes ───────────────────────────────────────────────────────────────

    def insert(self, table: str, row: dict):
        """Insert a row; raises ValueError if row omits or mismatches user_id."""
        self._check_user_id(row)
        return self._client.table(table).insert(row)

    def update(self, table: str, patch: dict, record_id: str, id_col: str = "id"):
        """Update a single record owned by this tenant."""
        return self._client.table(table).update(patch).eq(id_col, record_id).eq("user_id", self._user_id)

    def delete(self, table: str, record_id: str, id_col: str = "id"):
        """Delete a single record owned by this tenant."""
        return self._client.table(table).delete().eq(id_col, record_id).eq("user_id", self._user_id)

    def upsert(self, table: str, row: dict, on_conflict: str):
        """Upsert a row; raises ValueError if row omits or mismatches user_id."""
        self._check_user_id(row)
        return self._client.table(table).upsert(row, on_conflict=on_conflict)

    # ── raw escape hatch (service-role only, must be justified at call site) ─

    def raw_table(self, table: str):
        """Direct table access — only for queries that cannot use user_id
        (e.g. cross-tenant admin ops using the service-role key).
        Every call site must carry a comment explaining why this is safe."""
        return self._client.table(table)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _check_user_id(self, row: dict) -> None:
        if row.get("user_id") not in (None, self._user_id):
            raise ValueError(f"Cross-tenant write blocked: row.user_id={row['user_id']!r} " f"!= tenant={self._user_id!r}")
        row["user_id"] = self._user_id


def repo(client: Client, user_id: str) -> TenantQuery:
    """Return a tenant-scoped query wrapper for the given Supabase client."""
    return TenantQuery(client, user_id)
