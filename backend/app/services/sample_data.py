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

import hashlib
import re

from .. import store
from ..config import settings
from ..seed import build_seed

# ── Per-tenant variation ────────────────────────────────────────────────────
# Seeding every new tenant with a byte-identical business backfires: two people
# comparing screens see the same clients and the same totals and reasonably
# conclude the app leaks data between accounts. That impression is worse than an
# empty dashboard, because it reads as a security failure rather than a missing
# feature. (The rows are genuinely separate — different ids, correct user_id —
# it only *looks* shared.)
#
# So each tenant gets a different-looking business, derived deterministically
# from its own id: same tenant always regenerates the same sample, different
# tenants always differ.
#
# Client names are join keys — butler matches invoices to clients BY NAME — and
# they also appear inside generated email bodies and alert copy, as do the
# amounts. Renaming or rescaling only the structured fields would leave the text
# contradicting the data ("Blue Label LLC is 16 days late on $3,500" beside an
# invoice for a differently-named client). The transform therefore rewrites
# strings and numbers together, everywhere.
#
# Dates are deliberately NOT varied: overdue counts and the "16 days late"
# phrasing are pinned to the seeded due dates, and shifting them would break
# that agreement for no real gain once names and amounts already differ.
_ALT_CLIENT_NAMES = [
    "Northwind Traders",
    "Lumen Labs",
    "Bright Harbor",
    "Copper Lane Co",
    "Vantage Partners",
    "Ridgeline Group",
    "Solstice Media",
    "Ironwood Studio",
    "Fairview Collective",
    "Beacon & Co",
    "Marlowe Design",
    "Cascade Works",
    "Aster Consulting",
    "Halcyon Foods",
    "Kestrel Analytics",
]
_ALT_PEOPLE = ["Priya Raman", "Daniel Okafor", "Mia Fontaine", "Tomas Vela", "Ayesha Khan", "Jonas Berg"]

# Only fields that genuinely hold money get rescaled. A blanket "scale every
# float" would corrupt confidence scores, tax rates and quantities.
_MONEY_FIELDS = {
    "total",
    "subtotal",
    "tax",
    "tax_amount",
    "amount",
    "total_amount",
    "value",
    "balance",
    "price",
    "unit_price",
    "deposit",
    "deposit_amount",
    "monthly_amount",
    "retainer_amount",
}
_MONEY_IN_TEXT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")


def _tenant_seed(user_id: str) -> int:
    """Stable per-tenant integer. Deterministic so a re-seed reproduces itself."""
    return int(hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:8], 16)


def _scale_for(user_id: str) -> float:
    """A believable multiplier between 0.55x and 1.75x.

    Read from a DIFFERENT slice of the hash than `_tenant_seed`, so the amounts
    vary independently of the names — otherwise two tenants that happened to
    share a name rotation would share their totals as well. 121 steps rather
    than 25: the first attempt collided immediately in tests, and identical
    totals are exactly the coincidence this whole change exists to avoid.
    """
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return round(0.55 + (int(digest[8:16], 16) % 121) * 0.01, 2)


def _name_map(seed: int, originals: list[str]) -> dict[str, str]:
    """Map each seeded client name to a distinct alternative for this tenant."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    people_used = 0
    for i, original in enumerate(sorted(originals)):
        # A person's name in the seed (no corporate suffix) maps to a person.
        pool = _ALT_CLIENT_NAMES
        if not any(tok in original for tok in ("Corp", "LLC", "Co", "Agency", "Studio", "Inc", "Ltd")):
            pool = _ALT_PEOPLE
            idx = (seed + people_used) % len(pool)
            people_used += 1
        else:
            idx = (seed + i) % len(pool)
        # Walk forward on collision so two clients never collapse into one name.
        for step in range(len(pool)):
            candidate = pool[(idx + step) % len(pool)]
            if candidate not in used:
                break
        used.add(candidate)
        mapping[original] = candidate
    return mapping


def _rewrite_text(text: str, names: dict[str, str], scale: float) -> str:
    """Apply the same renaming and rescaling inside free text, so generated
    emails and alerts keep agreeing with the records they describe."""
    for original, replacement in names.items():
        text = text.replace(original, replacement)

    def _money(match: re.Match) -> str:
        raw = match.group(1).replace(",", "")
        try:
            scaled = round(float(raw) * scale, 2)
        except ValueError:
            return match.group(0)
        return f"${scaled:,.0f}" if scaled == int(scaled) else f"${scaled:,.2f}"

    return _MONEY_IN_TEXT.sub(_money, text)


def _vary(value, names: dict[str, str], scale: float, field: str | None = None):
    """Recursively rewrite one value: strings renamed, money rescaled."""
    if isinstance(value, str):
        return _rewrite_text(value, names, scale)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)) and field in _MONEY_FIELDS:
        return round(float(value) * scale, 2)
    if isinstance(value, list):
        return [_vary(v, names, scale, field) for v in value]
    if isinstance(value, dict):
        return {k: _vary(v, names, scale, k) for k, v in value.items()}
    if hasattr(value, "model_fields"):  # nested pydantic model (e.g. LineItem)
        for name in list(value.model_fields):
            setattr(value, name, _vary(getattr(value, name, None), names, scale, name))
    return value


def _personalize(data: dict, user_id: str) -> dict:
    """Give this tenant a business that looks like its own."""
    seed = _tenant_seed(user_id)
    scale = _scale_for(user_id)
    originals = [c.name for c in data.get("clients", []) if getattr(c, "name", None)]
    names = _name_map(seed, originals)

    for key, records in data.items():
        if key == "users":  # the tenant's own profile comes from onboarding
            continue
        for record in records:
            _vary(record, names, scale)
    return data


# Insert order is FK order: parents before the rows that reference them.
# Contracts precede invoices (an invoice may carry contract_id); clients precede
# engagements, notes, proposals and retainers.
def _insert_all(user_id: str) -> dict[str, int]:
    data = _personalize(build_seed(user_id), user_id)
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
