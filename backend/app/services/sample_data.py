"""Give a brand-new account something for the agents to reason about.

A fresh signup lands on an empty dashboard: no clients, no invoices, no
transactions. Every agent in Kora reasons *over* the user's business, so an
empty tenant makes the product look inert — the chase-the-overdue-invoice, the
cashflow forecast and the client brief all correctly render nothing.

`seed_sample_workspace` copies the demo dataset into a real tenant so the app
has a working business on first login. It reuses `build_seed`, so the sample is
the same internally consistent one the demo account uses — contracts linked to
their milestone invoices, engagements to their clients — rather than a second,
drifting fixture.

Deliberately OFF by default (`SEED_SAMPLE_DATA_ON_SIGNUP`). Inventing clients
and invoices inside a real person's books is the kind of thing that must be an
explicit operator decision, not a default: someone signing up to run their
actual business should get their actual business, empty until they fill it.
It is enabled for the public evaluation deployment, where the opposite is true
and an empty tenant shows a judge nothing.

Never raises. Seeding is a nicety; failing it must not break onboarding.
"""

from __future__ import annotations

from .. import store
from ..config import settings
from ..seed import build_seed


# Insert order is FK order: parents before the rows that reference them.
# Contracts precede invoices (an invoice may carry contract_id); clients precede
# engagements, notes, proposals and retainers.
def _insert_all(user_id: str) -> dict[str, int]:
    data = build_seed(user_id)
    counts: dict[str, int] = {}

    def step(name: str, rows: list, insert) -> None:
        """Best-effort per group: a table missing its migration skips that group
        instead of aborting the ones that would have succeeded."""
        try:
            for row in rows:
                insert(row)
            counts[name] = len(rows)
        except Exception as exc:  # pragma: no cover - depends on live schema
            counts[name] = 0
            print(f"[sample-data] {name}: skipped ({type(exc).__name__}: {str(exc)[:100]})")

    try:
        inserted = store.insert_transactions(data["transactions"])
        counts["transactions"] = len(inserted or data["transactions"])
    except Exception as exc:  # pragma: no cover - depends on live schema
        counts["transactions"] = 0
        print(f"[sample-data] transactions: skipped ({type(exc).__name__}: {str(exc)[:100]})")

    step("contracts", data.get("contracts", []), store.insert_contract)
    step("clients", data.get("clients", []), store.insert_client)
    step("engagements", data.get("engagements", []), store.insert_engagement)
    step("client_notes", data.get("client_notes", []), store.insert_client_note)
    step("proposals", data.get("proposals", []), store.insert_proposal)
    step("retainers", data.get("retainers", []), store.insert_retainer)
    step("invoices", data.get("invoices", []), store.insert_invoice)
    step("alerts", data.get("alerts", []), store.insert_alert)
    step("agent_logs", data.get("agent_logs", []), store.insert_agent_log)
    return counts


def seed_sample_workspace(user_id: str) -> dict | None:
    """Populate an empty tenant with the sample business.

    Returns the per-table counts, or None when the seed was declined (feature
    off, or the tenant already holds data). Refusing to touch a non-empty tenant
    is what keeps this safe to call more than once: onboarding_completed can be
    re-sent, and a second call must never duplicate a client list or bury rows
    the user created themselves.
    """
    if not settings.SEED_SAMPLE_DATA_ON_SIGNUP:
        return None
    if not user_id:
        return None

    try:
        if store.list_clients(user_id):
            return None
    except Exception as exc:  # pragma: no cover - depends on live schema
        # Unreadable tenant: refuse rather than risk seeding on top of data we
        # simply failed to see.
        print(f"[sample-data] emptiness check failed, not seeding ({type(exc).__name__}: {str(exc)[:100]})")
        return None

    try:
        counts = _insert_all(user_id)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[sample-data] seed aborted ({type(exc).__name__}: {str(exc)[:120]})")
        return None

    print(f"[sample-data] seeded tenant {user_id}: {counts}")
    return counts
