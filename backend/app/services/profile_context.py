"""Profile → LLM context.

Renders the rich, six-domain BusinessProfile into a compact, prioritized text
block for prompt injection. Task-aware: email/contract tasks foreground the brand
voice + guarantees; briefing/chat foreground offerings + customers + goals.

Kept dependency-light (no store/LLM calls) so any agent can call it cheaply. It
is the single place that decides *what of the profile the model sees*, so agents
stay consistent. Consumed by `playbook.assemble_context` (Tier 1) and the
generation agents (invoice/contract/proposal/gmail).
"""
from __future__ import annotations

from typing import Any

from ..models import BusinessProfile, normalize_business_type


def _as_dict(profile: Any) -> dict:
    if profile is None:
        return {}
    if isinstance(profile, BusinessProfile):
        return profile.model_dump(by_alias=False)
    if hasattr(profile, "model_dump"):
        return profile.model_dump(by_alias=False)
    return dict(profile) if isinstance(profile, dict) else {}


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _joined(items: Any, limit: int = 6) -> str:
    if not isinstance(items, (list, tuple)):
        return ""
    vals = [str(x).strip() for x in items if str(x).strip()]
    return ", ".join(vals[:limit])


# Which optional domains matter for each business type (drives what we surface).
# Mirrors the frontend templates.ts so agent context matches the UI the owner fills.
_TYPE_SECTIONS: dict[str, set[str]] = {
    "freelancer": {"brand", "offerings", "customers"},
    "online_seller": {"brand", "offerings", "customers", "marketing"},
    "small_business": {"brand", "offerings", "customers", "operations", "marketing"},
    "agency": {"brand", "offerings", "customers", "operations", "marketing"},
    "startup": {"brand", "offerings", "customers", "operations", "marketing"},
}


def build_profile_brief(
    profile: Any,
    task_type: str = "briefing",
    *,
    business_name: str | None = None,
    max_chars: int = 700,
) -> str:
    """Return a compact multi-line business brief for prompt injection, or "".

    task_type: "briefing" | "chat" | "email_draft" | "follow_up_decision" |
               "contract" | "proposal" | "forecast" | "categorization"
    """
    p = _as_dict(profile)
    if not p and not business_name:
        return ""

    btype = normalize_business_type(p.get("business_type")) or ""
    sections = _TYPE_SECTIONS.get(btype, {"brand", "offerings", "customers"})
    is_writing = task_type in ("email_draft", "follow_up_decision", "contract", "proposal")

    lines: list[str] = []

    # ── Identity (always) ────────────────────────────────────────────────
    ident: list[str] = []
    bname = _s(business_name) or _s(p.get("business_name"))
    if bname:
        ident.append(bname)
    if btype:
        ident.append(f"({btype.replace('_', ' ')})")
    if _s(p.get("industry")):
        ident.append(f"in {_s(p['industry'])}")
    if _s(p.get("role_title")):
        ident.append(f"— {_s(p['role_title'])}")
    if ident:
        lines.append(" ".join(ident) + ".")
    if _s(p.get("description")):
        lines.append(_s(p["description"]))

    # ── Brand ────────────────────────────────────────────────────────────
    brand = p.get("brand") or {}
    if isinstance(brand, dict) and "brand" in sections:
        # Voice matters most for anything the model writes.
        voice = _s(brand.get("voice")) or _s(p.get("brand_tone"))
        if voice:
            lines.append(f"Brand voice: {voice}.")
        if _s(brand.get("usp")):
            lines.append(f"USP: {_s(brand['usp'])}.")
        if not is_writing and _joined(brand.get("values")):
            lines.append(f"Values: {_joined(brand.get('values'))}.")

    # ── Offerings ────────────────────────────────────────────────────────
    offerings = p.get("offerings") or []
    if isinstance(offerings, list) and offerings and "offerings" in sections:
        pieces = []
        for off in offerings[:3]:
            if not isinstance(off, dict):
                continue
            name = _s(off.get("name"))
            if not name:
                continue
            price = _s(off.get("pricing"))
            pieces.append(f"{name}" + (f" ({price})" if price else ""))
            if is_writing and _s(off.get("guarantees")):
                lines.append(f"Guarantee ({name}): {_s(off['guarantees'])}.")
        if pieces:
            lines.append("Offerings: " + "; ".join(pieces) + ".")

    # ── Customers ────────────────────────────────────────────────────────
    cust = p.get("customers") or {}
    if isinstance(cust, dict) and "customers" in sections and not is_writing:
        personas = cust.get("buyer_personas") or []
        if isinstance(personas, list) and personas:
            first = personas[0] if isinstance(personas[0], dict) else {}
            pname = _s(first.get("name"))
            if pname:
                lines.append(f"Primary customer: {pname}" + (f" — {_s(first.get('description'))}" if _s(first.get("description")) else "") + ".")
        if _joined(cust.get("industries_served")):
            lines.append(f"Serves: {_joined(cust.get('industries_served'))}.")
    # Fallback to the legacy flat field.
    if not (isinstance(cust, dict) and cust.get("buyer_personas")) and _s(p.get("target_clients")) and not is_writing:
        lines.append(f"Target clients: {_s(p['target_clients'])}.")

    # ── Operations (team-ish types only) ─────────────────────────────────
    ops = p.get("operations") or {}
    if isinstance(ops, dict) and "operations" in sections and not is_writing:
        team = ops.get("team_members") or []
        if isinstance(team, list) and team:
            lines.append(f"Team of {len(team)}.")
        if _joined(ops.get("tools"), limit=5):
            lines.append(f"Tools: {_joined(ops.get('tools'), limit=5)}.")

    # ── Marketing ────────────────────────────────────────────────────────
    mkt = p.get("marketing") or {}
    if isinstance(mkt, dict) and "marketing" in sections and not is_writing:
        if _joined(mkt.get("competitors"), limit=4):
            lines.append(f"Competitors: {_joined(mkt.get('competitors'), limit=4)}.")

    # ── Goals (briefing / chat) ──────────────────────────────────────────
    if task_type in ("briefing", "chat", "forecast"):
        if p.get("monthly_revenue_goal"):
            try:
                lines.append(f"Monthly revenue goal: ${float(p['monthly_revenue_goal']):,.0f}.")
            except (TypeError, ValueError):
                pass
        if _s(p.get("financial_goals")):
            lines.append(f"Goals: {_s(p['financial_goals'])}.")

    # ── Dedup + truncate ─────────────────────────────────────────────────
    seen: set[str] = set()
    unique: list[str] = []
    for ln in lines:
        norm = ln.strip().lower()
        if ln.strip() and norm not in seen:
            seen.add(norm)
            unique.append(ln.strip())

    combined = "\n".join(unique)
    while len(combined) > max_chars and unique:
        unique.pop()
        combined = "\n".join(unique)
    return combined
