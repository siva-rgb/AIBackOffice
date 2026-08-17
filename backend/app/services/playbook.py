"""
Business Playbook — observation, assembly, and pattern detection.

Passively watches user actions (approve/dismiss, corrections, email edits,
payments) and stores what it learns. Later, assemble_context() retrieves the
most relevant learned facts and injects them into LLM prompts so every agent
gets personalized context for free.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .. import store
from . import agent_logger


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVER 1: Approve / Dismiss decisions
# ═══════════════════════════════════════════════════════════════════════════


def observe_decision(user_id: str, task: dict, action: str) -> None:
    """Record a manager task approve/dismiss. Builds approval-rate entries and
    detects business rules from repeated dismiss patterns.

    Wire: routers/manager.py → approve() and dismiss() after supervisor call.
    """
    kind = task.get("kind", "")
    client_id = task.get("payload", {}).get("client_id") or task.get("payload", {}).get("related_client_id")

    store.upsert_playbook_entry(
        user_id,
        {
            "category": "user_preference",
            "client_id": client_id,
            "key": f"decision_{kind}_{action}",
            "value": {"kind": kind, "action": action, "task_title": task.get("title", "")},
            "summary": f"User {action} a '{kind}' action" + (" for client" if client_id else ""),
            "source": "observation",
            "confidence": 0.3,
        },
    )

    # Detect business rules from repeated dismissals (3+)
    if action == "dismissed":
        history = store.get_playbook_entries(user_id, category="user_preference", client_id=client_id)
        dismiss_count = sum(1 for e in history if e.get("key", "").startswith(f"decision_{kind}_dismissed") and e.get("observation_count", 0) >= 3)
        if dismiss_count > 0:
            rule_key = f"skip_{kind}" + (f"_client_{client_id}" if client_id else "")
            store.upsert_playbook_entry(
                user_id,
                {
                    "category": "business_rule",
                    "client_id": client_id,
                    "key": rule_key,
                    "value": {"kind": kind, "reason": "repeatedly dismissed"},
                    "summary": (f"User consistently dismisses '{kind}' actions" + (" for this client" if client_id else "") + ", so stop proposing them"),
                    "source": "observation",
                    "confidence": 0.7,
                },
            )


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVER 2: Category corrections (bookkeeping)
# ═══════════════════════════════════════════════════════════════════════════


def observe_correction(
    user_id: str,
    transaction_id: str,
    description: str,
    old_category: str,
    new_category: str,
) -> None:
    """Record a manual transaction category change as a permanent correction
    (confidence 1.0, never decays).

    Wire: routers/bookkeeping.py PATCH /transactions/{id}/category endpoint.
    """
    if old_category == new_category:
        return

    desc_key = _normalize_description(description)
    store.upsert_playbook_entry(
        user_id,
        {
            "category": "correction",
            "client_id": None,
            "key": f"category_override_{desc_key}",
            "value": {
                "description_pattern": desc_key,
                "original_description": description,
                "old_category": old_category,
                "new_category": new_category,
            },
            "summary": f'"{desc_key}" should be categorized as {new_category} (corrected from {old_category})',
            "source": "correction",
            "confidence": 1.0,
        },
    )

    try:
        agent_logger.log_action(
            user_id=user_id,
            agent_type="playbook",
            action=f"Recorded category correction: {desc_key} → {new_category}",
            input={"transaction_id": transaction_id, "old": old_category},
            output={"new": new_category},
            triggered_by="user",
        )
    except Exception:
        pass


def _normalize_description(desc: str) -> str:
    clean = desc.upper().strip()
    clean = re.sub(r"[*#]\S+", "", clean)
    clean = re.sub(r"\d{4,}", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    words = clean.split()[:3]
    return " ".join(words).lower()


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVER 3: Email draft edits
# ═══════════════════════════════════════════════════════════════════════════


def observe_email_edit(
    user_id: str,
    original_body: str,
    edited_body: str,
    client_id: str | None = None,
) -> None:
    """Extract tone/style signals when user edits an email draft before approving.

    Wire: routers/manager.py → approve() when kind == 'send_email_gmail' and
    payload contains an edited body different from the original.
    """
    if not original_body or not edited_body:
        return
    if original_body.strip() == edited_body.strip():
        return

    signals: dict = {}

    # Length preference
    orig_words = len(original_body.split())
    edit_words = len(edited_body.split())
    if edit_words < orig_words * 0.7:
        signals["length_preference"] = "shorter"
    elif edit_words > orig_words * 1.3:
        signals["length_preference"] = "longer"

    # Formality
    edit_lower = edited_body.lower()
    informal_markers = ["hey", "hi ", "thanks!", "cheers", "lol", "haha"]
    formal_markers = ["dear", "regards", "sincerely", "respectfully"]
    has_informal = any(m in edit_lower for m in informal_markers)
    has_formal = any(m in edit_lower for m in formal_markers)
    if has_informal and not has_formal:
        signals["tone"] = "casual"
    elif has_formal and not has_informal:
        signals["tone"] = "formal"

    # Greeting pattern
    first_line = edited_body.strip().split("\n")[0].strip().lower()
    if first_line.startswith("hi "):
        signals["greeting_style"] = "hi_firstname"
    elif first_line.startswith("hey "):
        signals["greeting_style"] = "hey_firstname"
    elif first_line.startswith("dear "):
        signals["greeting_style"] = "dear_firstname"

    if not signals:
        return

    store.upsert_playbook_entry(
        user_id,
        {
            "category": "user_preference",
            "client_id": client_id,
            "key": "email_style" + (f"_client_{client_id}" if client_id else ""),
            "value": signals,
            "summary": _build_style_summary(signals),
            "source": "observation",
            "confidence": 0.4,
        },
    )


def _build_style_summary(signals: dict) -> str:
    parts = []
    if "length_preference" in signals:
        parts.append(f"prefers {signals['length_preference']} emails")
    if "tone" in signals:
        parts.append(f"{signals['tone']} tone")
    if "greeting_style" in signals:
        parts.append(f"opens with '{signals['greeting_style'].replace('_', ' ')}'")
    return "User " + ", ".join(parts) if parts else ""


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVER 4: Payment reconciliation → client payment speed
# ═══════════════════════════════════════════════════════════════════════════


def observe_payment(user_id: str, invoice: dict, transaction: dict) -> None:
    """Record client payment speed after invoice reconciliation.

    Wire: services/cross_module.py → reconcile_payments() after marking paid.
    """
    client_name = invoice.get("client_name", "")
    if not client_name:
        return

    days_to_pay: int | None = None
    due_date = invoice.get("due_date")
    payment_date = transaction.get("date")
    if due_date and payment_date:
        try:
            due = datetime.fromisoformat(str(due_date).replace("Z", "+00:00")).date()
            paid = datetime.fromisoformat(str(payment_date).replace("Z", "+00:00")).date()
            days_to_pay = (paid - due).days
        except Exception:
            pass

    clients = store.list_clients(user_id)
    matched = next((c for c in clients if c.name.lower() == client_name.lower()), None)
    client_id = matched.id if matched else None

    speed = (
        "early"
        if days_to_pay is not None and days_to_pay < 0
        else "on_time" if days_to_pay is not None and days_to_pay <= 3 else "late" if days_to_pay is not None else "unknown"
    )

    store.upsert_playbook_entry(
        user_id,
        {
            "category": "client_intelligence",
            "client_id": client_id,
            "key": "payment_speed",
            "value": {
                "client_name": client_name,
                "days_to_pay": days_to_pay,
                "speed": speed,
                "invoice_amount": invoice.get("total"),
                "follow_up_count": invoice.get("follow_up_count", 0),
            },
            "summary": (
                f"{client_name} paid {'early' if speed == 'early' else f'{days_to_pay} days after due date'}"
                + (f" after {invoice.get('follow_up_count', 0)} reminder(s)" if invoice.get("follow_up_count") else "")
            ),
            "source": "observation",
            "confidence": 0.5,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVER 5: Gmail intel bridge (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════


def observe_email_intel(user_id: str, client_id: str, intel: dict) -> None:
    """Bridge gmail_intel_cache data into the Playbook.

    Wire: services/gmail_intel.py → _process_client_threads() after cache upsert.
    """
    client_name = intel.get("client_name", "")

    for mention in intel.get("financial_mentions", []):
        if mention.get("amount") and mention.get("type"):
            store.upsert_playbook_entry(
                user_id,
                {
                    "category": "extracted_fact",
                    "client_id": client_id,
                    "key": f"financial_mention_{mention['type']}",
                    "value": mention,
                    "summary": (
                        f"{client_name}: {mention['type']} of ${mention['amount']:,.0f} mentioned in email"
                        if isinstance(mention.get("amount"), (int, float))
                        else f"{client_name}: {mention.get('context', '')}"
                    ),
                    "source": "extraction",
                    "confidence": 0.6,
                },
            )

    for commitment in intel.get("commitments_pending", []):
        who = commitment.get("who", "")
        what = commitment.get("what", "")
        if what:
            store.upsert_playbook_entry(
                user_id,
                {
                    "category": "extracted_fact",
                    "client_id": client_id,
                    "key": f"commitment_{who}",
                    "value": commitment,
                    "summary": (
                        f"{client_name}: {who} committed to '{what}'" + (f" by {commitment['mentioned_date']}" if commitment.get("mentioned_date") else "")
                    ),
                    "source": "extraction",
                    "confidence": 0.55,
                },
            )

    if intel.get("relationship_health") and intel["relationship_health"] != "unknown":
        store.upsert_playbook_entry(
            user_id,
            {
                "category": "client_intelligence",
                "client_id": client_id,
                "key": "email_relationship_health",
                "value": {
                    "health": intel["relationship_health"],
                    "sentiment": intel.get("sentiment"),
                    "last_contact_days": intel.get("last_contact_days"),
                },
                "summary": (
                    f"{client_name}: email relationship is {intel['relationship_health']}"
                    + (f" (sentiment: {intel['sentiment']})" if intel.get("sentiment") else "")
                ),
                "source": "extraction",
                "confidence": 0.6,
            },
        )

    # Task ledger — pending commitments become tracked work so nothing promised
    # over email is dropped. Idempotent per (client, who, what).
    try:
        from .task_ledger import auto_capture_from_email

        auto_capture_from_email(user_id, client_id, intel)
    except Exception:
        pass

    # Graph memory bridge — make learned email facts traversable per client.
    try:
        from .graph_memory import ingest_client_fact

        for commitment in intel.get("commitments_pending", []):
            what = commitment.get("what")
            if what:
                ingest_client_fact(user_id, client_id, client_name, f"{commitment.get('who', '')} committed to '{what}'".strip(), source="email")
        if intel.get("relationship_health") and intel["relationship_health"] != "unknown":
            ingest_client_fact(user_id, client_id, client_name, f"Email relationship: {intel['relationship_health']}", rel="RELATED_TO", source="email")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVER 6: Meeting agent bridge (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════


def observe_meeting(user_id: str, client_id: str | None, extracted: dict) -> None:
    """Bridge meeting MOM data into the Playbook.

    Wire: services/meeting_agent.py → process_transcript() after DB update.
    """
    if not client_id:
        return

    for mention in extracted.get("financial_mentions", []):
        if mention.get("amount"):
            store.upsert_playbook_entry(
                user_id,
                {
                    "category": "extracted_fact",
                    "client_id": client_id,
                    "key": f"meeting_financial_{mention.get('type', 'unknown')}",
                    "value": mention,
                    "summary": (
                        f"Meeting mentioned: {mention.get('type', '')} ${mention['amount']:,.0f}"
                        + (f", {mention.get('context', '')}" if mention.get("context") else "")
                    ),
                    "source": "extraction",
                    "confidence": 0.65,
                },
            )

    for commitment in extracted.get("commitments", []):
        if commitment.get("who") == "client" and commitment.get("what"):
            store.upsert_playbook_entry(
                user_id,
                {
                    "category": "extracted_fact",
                    "client_id": client_id,
                    "key": "client_commitment",
                    "value": commitment,
                    "summary": (f"Client committed: {commitment['what']}" + (f" by {commitment['by_when']}" if commitment.get("by_when") else "")),
                    "source": "extraction",
                    "confidence": 0.7,
                },
            )

    # Graph memory bridge — meeting commitments become traversable client facts.
    try:
        from .graph_memory import ingest_client_fact

        for commitment in extracted.get("commitments", []):
            if commitment.get("who") == "client" and commitment.get("what"):
                ingest_client_fact(user_id, client_id, None, f"Committed in meeting: {commitment['what']}", rel="MET_ABOUT", source="meeting")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVER 7: Onboarding seed
# ═══════════════════════════════════════════════════════════════════════════


def seed_from_onboarding(user_id: str, profile: dict) -> None:
    """Seed the Playbook with initial business context from the onboarding profile.

    Wire: routers/users.py → update_me() when onboarding_completed = True.
    """
    if not profile:
        return

    if profile.get("business_type"):
        store.upsert_playbook_entry(
            user_id,
            {
                "category": "extracted_fact",
                "key": "business_type",
                "value": {"type": profile["business_type"]},
                "summary": f"Business type: {profile['business_type']}",
                "source": "onboarding",
                "confidence": 1.0,
            },
        )

    if profile.get("industry"):
        store.upsert_playbook_entry(
            user_id,
            {
                "category": "extracted_fact",
                "key": "industry",
                "value": {"industry": profile["industry"]},
                "summary": f"Industry: {profile['industry']}",
                "source": "onboarding",
                "confidence": 1.0,
            },
        )

    if profile.get("monthly_revenue_goal"):
        store.upsert_playbook_entry(
            user_id,
            {
                "category": "business_pattern",
                "key": "monthly_revenue_goal",
                "value": {"goal": profile["monthly_revenue_goal"]},
                "summary": f"Monthly revenue goal: ${profile['monthly_revenue_goal']:,.0f}",
                "source": "onboarding",
                "confidence": 1.0,
            },
        )

    if profile.get("default_payment_terms_days"):
        store.upsert_playbook_entry(
            user_id,
            {
                "category": "user_preference",
                "key": "default_payment_terms",
                "value": {"terms_days": profile["default_payment_terms_days"]},
                "summary": f"Default payment terms: Net {profile['default_payment_terms_days']}",
                "source": "onboarding",
                "confidence": 0.9,
            },
        )

    if profile.get("default_hourly_rate"):
        store.upsert_playbook_entry(
            user_id,
            {
                "category": "extracted_fact",
                "key": "hourly_rate",
                "value": {"rate": profile["default_hourly_rate"], "currency": profile.get("currency", "USD")},
                "summary": f"Standard hourly rate: ${profile['default_hourly_rate']}/hour",
                "source": "onboarding",
                "confidence": 0.9,
            },
        )

    if profile.get("brand_tone"):
        store.upsert_playbook_entry(
            user_id,
            {
                "category": "user_preference",
                "key": "brand_tone",
                "value": {"tone": profile["brand_tone"]},
                "summary": f"Communication tone: {profile['brand_tone']}",
                "source": "onboarding",
                "confidence": 0.9,
            },
        )

    # Rich six-domain profile → high-signal facts (v2 profile).
    brand = profile.get("brand") or {}
    if isinstance(brand, dict):
        if brand.get("voice"):
            store.upsert_playbook_entry(
                user_id,
                {
                    "category": "user_preference",
                    "key": "brand_voice",
                    "value": {"voice": brand["voice"]},
                    "summary": f"Brand voice: {brand['voice']}",
                    "source": "onboarding",
                    "confidence": 0.9,
                },
            )
        if brand.get("usp"):
            store.upsert_playbook_entry(
                user_id,
                {
                    "category": "extracted_fact",
                    "key": "usp",
                    "value": {"usp": brand["usp"]},
                    "summary": f"Unique selling proposition: {brand['usp']}",
                    "source": "onboarding",
                    "confidence": 0.9,
                },
            )

    offerings = profile.get("offerings") or []
    if isinstance(offerings, list) and offerings:
        first = offerings[0] if isinstance(offerings[0], dict) else {}
        if first.get("name"):
            price = f" ({first['pricing']})" if first.get("pricing") else ""
            store.upsert_playbook_entry(
                user_id,
                {
                    "category": "extracted_fact",
                    "key": "primary_offering",
                    "value": {"name": first["name"], "pricing": first.get("pricing")},
                    "summary": f"Primary offering: {first['name']}{price}",
                    "source": "onboarding",
                    "confidence": 0.85,
                },
            )

    customers = profile.get("customers") or {}
    personas = customers.get("buyer_personas") if isinstance(customers, dict) else None
    if isinstance(personas, list) and personas and isinstance(personas[0], dict) and personas[0].get("name"):
        store.upsert_playbook_entry(
            user_id,
            {
                "category": "client_intelligence",
                "key": "primary_persona",
                "value": {"name": personas[0]["name"], "description": personas[0].get("description")},
                "summary": f"Primary customer persona: {personas[0]['name']}",
                "source": "onboarding",
                "confidence": 0.8,
            },
        )


# ═══════════════════════════════════════════════════════════════════════════
# CONTEXT ASSEMBLER
# ═══════════════════════════════════════════════════════════════════════════


def assemble_context(
    user_id: str,
    task_type: str,
    client_id: str | None = None,
    max_chars: int = 1500,
) -> str:
    """Return a plain text Business Context block for LLM prompt injection.

    task_type: "briefing" | "email_draft" | "follow_up_decision" |
               "categorization" | "contract" | "forecast" | "proposal"

    Returns "" for day-1 users with no Playbook data (safe to inject always).
    """
    parts: list[str] = []

    # ── Tier 1: Business brief (identity + brand/offerings/customers/goals) ─
    user = store.get_user(user_id)
    if user:
        from .profile_context import build_profile_brief

        brief = build_profile_brief(
            user.profile,
            task_type,
            business_name=getattr(user, "business_name", None),
            max_chars=700,
        )
        if brief:
            parts.append(brief)

    # ── Tier 2: kora_memory cache or live Playbook query ─────────────────
    kora_memory: dict = {}
    if user and hasattr(user, "profile"):
        raw_mem = getattr(user, "kora_memory", None)
        if isinstance(raw_mem, dict):
            kora_memory = raw_mem

    used_memory_cache = False
    if kora_memory.get("top_preferences"):
        parts.extend(kora_memory["top_preferences"][:3])
        used_memory_cache = True
    if kora_memory.get("top_rules"):
        parts.extend(kora_memory["top_rules"][:2])
        used_memory_cache = True

    if not used_memory_cache:
        for pref in store.get_playbook_entries(user_id, category="user_preference", min_confidence=0.6, limit=5):
            if pref.get("summary"):
                parts.append(pref["summary"])
        for rule in store.get_playbook_entries(user_id, category="business_rule", min_confidence=0.6, limit=3):
            if rule.get("summary"):
                parts.append(rule["summary"])

    # Corrections — always live query
    corrections = store.get_playbook_corrections(user_id)
    if corrections:
        summaries = [c["summary"] for c in corrections[:5] if c.get("summary")]
        if summaries:
            parts.append("Corrections: " + "; ".join(summaries) + ".")

    # ── Tier 3: Task-specific context ────────────────────────────────────
    if task_type == "email_draft" and client_id:
        for entry in store.get_playbook_for_client(user_id, client_id)[:5]:
            if entry.get("summary"):
                parts.append(entry["summary"])

    elif task_type == "follow_up_decision" and client_id:
        client_entries = store.get_playbook_for_client(user_id, client_id)
        for entry in [e for e in client_entries if "payment" in e.get("key", "") or "decision" in e.get("key", "")][:3]:
            if entry.get("summary"):
                parts.append(entry["summary"])
        for rule in [e for e in client_entries if e.get("category") == "business_rule" and "skip" in e.get("key", "")][:2]:
            if rule.get("summary"):
                parts.append(rule["summary"])

    elif task_type == "forecast":
        if kora_memory.get("top_patterns"):
            parts.extend(kora_memory["top_patterns"][:3])
        else:
            for p in store.get_playbook_entries(user_id, category="business_pattern", min_confidence=0.5, limit=5):
                if p.get("summary"):
                    parts.append(p["summary"])

    elif task_type in ("contract", "proposal"):
        for pref in store.get_playbook_entries(user_id, category="user_preference", min_confidence=0.5, limit=5):
            if any(k in pref.get("key", "") for k in ("payment_terms", "brand_tone", "hourly_rate")):
                if pref.get("summary"):
                    parts.append(pref["summary"])
        for f in store.get_playbook_entries(user_id, category="extracted_fact", min_confidence=0.6, limit=3):
            if any(k in f.get("key", "") for k in ("hourly_rate", "business_type")):
                if f.get("summary"):
                    parts.append(f["summary"])
        if client_id:
            for entry in store.get_playbook_for_client(user_id, client_id)[:3]:
                if entry.get("summary"):
                    parts.append(entry["summary"])

    elif task_type == "briefing":
        if kora_memory.get("top_patterns"):
            parts.extend(kora_memory["top_patterns"][:3])
        else:
            for p in store.get_playbook_entries(user_id, category="business_pattern", min_confidence=0.5, limit=3):
                if p.get("summary"):
                    parts.append(p["summary"])
        if kora_memory.get("top_client_intel"):
            parts.extend(kora_memory["top_client_intel"][:3])
        else:
            for ci in store.get_playbook_entries(user_id, category="client_intelligence", min_confidence=0.6, limit=3):
                if ci.get("summary"):
                    parts.append(ci["summary"])
        if kora_memory.get("top_facts"):
            parts.extend(kora_memory["top_facts"][:3])
        else:
            for f in store.get_playbook_entries(user_id, category="extracted_fact", min_confidence=0.6, limit=3):
                if f.get("summary"):
                    parts.append(f["summary"])

    # ── Graph memory tier: linked entities & relationships ───────────────
    if task_type in ("briefing", "chat", "email_draft", "follow_up_decision", "contract", "proposal"):
        try:
            from .graph_memory import build_graph_brief

            graph_brief = build_graph_brief(user_id, task_type, client_id=client_id, max_chars=500)
            if graph_brief:
                parts.append(graph_brief)
        except Exception:
            pass

    # ── Task ledger tier: what's actually open right now ─────────────────
    # Comes before recall so the agent never promises something that's blocked
    # or forgets an overdue commitment.
    if task_type in ("briefing", "chat", "email_draft", "follow_up_decision", "proposal"):
        try:
            from .task_ledger import build_task_brief

            task_brief = build_task_brief(user_id, client_id=client_id, max_chars=450)
            if task_brief:
                parts.append(task_brief)
        except Exception:
            pass

    # ── Semantic recall tier: relevant PAST context by meaning ───────────
    # Most valuable when there's a focus to query on (a client, or a writing
    # task). The query is synthesized from the task + client so recall surfaces
    # memories related to what the agent is doing right now.
    if task_type in ("briefing", "chat", "email_draft", "follow_up_decision", "contract", "proposal"):
        try:
            from .memory_recall import build_recall_brief

            q_bits = [task_type.replace("_", " ")]
            if client_id:
                cc = store.get_client(user_id, client_id)
                if cc and getattr(cc, "name", None):
                    q_bits.append(cc.name)
            elif task_type in ("briefing", "chat"):
                q_bits.append("priorities risks overdue payments client relationships")
            recall_brief = build_recall_brief(
                user_id,
                " ".join(q_bits),
                client_id=client_id,
                max_chars=400,
            )
            if recall_brief:
                parts.append(recall_brief)
        except Exception:
            pass

    # ── Compress to max_chars ─────────────────────────────────────────────
    if not parts:
        return ""

    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        norm = p.strip().lower()
        if norm not in seen:
            seen.add(norm)
            unique.append(p.strip())

    combined = "\n".join(unique)
    while len(combined) > max_chars and unique:
        unique.pop()
        combined = "\n".join(unique)

    return combined


def apply_corrections_before_llm(user_id: str, transactions: list) -> tuple[list, list]:
    """Split transactions into (already_corrected, needs_llm) using Playbook corrections.

    Corrected transactions skip the LLM entirely (saves tokens + cost).
    Wire: services/bookkeeper.py → ingest_transactions() before LLM batch call.
    """
    corrections = store.get_playbook_corrections(user_id)
    correction_map: dict[str, str] = {}
    for c in corrections:
        if c.get("key", "").startswith("category_override_"):
            pattern = c.get("value", {}).get("description_pattern", "")
            new_cat = c.get("value", {}).get("new_category", "")
            if pattern and new_cat:
                correction_map[pattern] = new_cat

    if not correction_map:
        return [], list(transactions)

    already_corrected: list = []
    needs_llm: list = []
    for txn in transactions:
        desc = txn.description if hasattr(txn, "description") else txn.get("description", "")
        desc_key = _normalize_description(desc)
        if desc_key in correction_map:
            if hasattr(txn, "category"):
                txn.category = correction_map[desc_key]
                txn.ai_categorized = True
                txn.ai_confidence = 1.0
            else:
                txn = dict(txn)
                txn["category"] = correction_map[desc_key]
                txn["ai_categorized"] = True
                txn["ai_confidence"] = 1.0
            already_corrected.append(txn)
        else:
            needs_llm.append(txn)

    return already_corrected, needs_llm


def compress_playbook_to_memory(user_id: str) -> dict:
    """Roll up top Playbook entries into kora_memory JSONB on users table.

    Called weekly or on demand via POST /api/playbook/compress.
    """
    entries = store.get_playbook_entries(user_id, min_confidence=0.5, limit=30)

    by_category: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if e.get("summary"):
            by_category[e.get("category", "")].append(e["summary"])

    memory = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_entries": len(entries),
        "corrections_count": len([e for e in entries if e.get("category") == "correction"]),
        "top_preferences": by_category.get("user_preference", [])[:3],
        "top_patterns": by_category.get("business_pattern", [])[:3],
        "top_rules": by_category.get("business_rule", [])[:2],
        "top_client_intel": by_category.get("client_intelligence", [])[:3],
        "top_facts": by_category.get("extracted_fact", [])[:3],
    }

    try:
        store.update_user(user_id, {"kora_memory": memory})
    except Exception:
        pass

    return memory


# ═══════════════════════════════════════════════════════════════════════════
# PATTERN DETECTION (on-demand)
# ═══════════════════════════════════════════════════════════════════════════


def detect_patterns(user_id: str) -> list[dict]:
    """Analyze transaction and client history for patterns.

    Called via POST /api/playbook/detect or manually.
    Returns list of newly detected pattern dicts.
    """
    detected: list[dict] = []
    detected.extend(_detect_client_payment_patterns(user_id))
    detected.extend(_detect_income_seasonality(user_id))
    detected.extend(_detect_billing_rhythm(user_id))
    detected.extend(_detect_communication_frequency(user_id))
    return detected


def _detect_client_payment_patterns(user_id: str) -> list[dict]:
    patterns: list[dict] = []
    invoices = store.list_invoices(user_id)
    if not invoices:
        return patterns

    by_client: dict[str, list] = defaultdict(list)
    for inv in invoices:
        name = inv.client_name if hasattr(inv, "client_name") else inv.get("client_name", "")
        if name:
            by_client[name.lower()].append(inv)

    clients = store.list_clients(user_id)
    for client_name_lower, client_invs in by_client.items():
        if len(client_invs) < 3:
            continue
        paid = [i for i in client_invs if (i.status if hasattr(i, "status") else i.get("status")) == "paid"]
        overdue = [i for i in client_invs if (i.status if hasattr(i, "status") else i.get("status")) == "overdue"]
        total = len(client_invs)
        paid_pct = len(paid) / total
        reliability = "reliable" if paid_pct > 0.8 else "mixed" if paid_pct > 0.5 else "unreliable"

        matched = next((c for c in clients if c.name.lower() == client_name_lower), None)
        client_id = matched.id if matched else None

        entry = {
            "category": "client_intelligence",
            "client_id": client_id,
            "key": "payment_reliability",
            "value": {
                "reliability": reliability,
                "paid_count": len(paid),
                "overdue_count": len(overdue),
                "total_invoices": total,
                "paid_percentage": round(paid_pct * 100),
            },
            "summary": f"Payment reliability: {reliability} ({round(paid_pct * 100)}% paid on time, {total} invoices)",
            "source": "pattern_detection",
            "confidence": min(0.9, 0.5 + (total * 0.05)),
        }
        store.upsert_playbook_entry(user_id, entry)
        patterns.append(entry)

    return patterns


def _detect_income_seasonality(user_id: str) -> list[dict]:
    patterns: list[dict] = []
    transactions = store.list_transactions(user_id)
    if not transactions:
        return patterns

    monthly_income: dict[str, float] = defaultdict(float)
    for txn in transactions:
        tx_type = txn.type if hasattr(txn, "type") else txn.get("type")
        tx_date = txn.date if hasattr(txn, "date") else txn.get("date", "")
        tx_amount = txn.amount if hasattr(txn, "amount") else txn.get("amount", 0)
        if tx_type == "income" and tx_date:
            monthly_income[tx_date[:7]] += abs(float(tx_amount))

    if len(monthly_income) < 3:
        return patterns

    values = list(monthly_income.values())
    avg = sum(values) / len(values)
    if avg == 0:
        return patterns

    for month, income in monthly_income.items():
        ratio = income / avg
        if ratio > 1.5:
            entry = {
                "category": "business_pattern",
                "key": f"high_income_month_{month[-2:]}",
                "value": {"month": month, "income": income, "vs_average": round(ratio, 1)},
                "summary": f"Month {month} had {round(ratio, 1)}x average income",
                "source": "pattern_detection",
                "confidence": 0.6,
            }
            store.upsert_playbook_entry(user_id, entry)
            patterns.append(entry)

    return patterns


def _detect_billing_rhythm(user_id: str) -> list[dict]:
    patterns: list[dict] = []
    invoices = store.list_invoices(user_id)
    if len(invoices) < 5:
        return patterns

    days_of_month: Counter = Counter()
    for inv in invoices:
        created = inv.created_at if hasattr(inv, "created_at") else inv.get("created_at", "")
        if created:
            try:
                day = datetime.fromisoformat(created.replace("Z", "+00:00")).day
                days_of_month[day] += 1
            except Exception:
                pass

    if not days_of_month:
        return patterns

    most_common_day, count = days_of_month.most_common(1)[0]
    if count >= 3:
        entry = {
            "category": "business_pattern",
            "key": "typical_billing_day",
            "value": {"day_of_month": most_common_day, "count": count},
            "summary": f"Typically creates invoices around day {most_common_day} of the month",
            "source": "pattern_detection",
            "confidence": min(0.85, 0.5 + (count * 0.07)),
        }
        store.upsert_playbook_entry(user_id, entry)
        patterns.append(entry)

    return patterns


def _detect_communication_frequency(user_id: str) -> list[dict]:
    """Detect per-client communication frequency from email_intel_cache if available."""
    patterns: list[dict] = []
    try:
        if not hasattr(store, "get_email_intel_cache"):
            return patterns
        cache = store.get_email_intel_cache(user_id)
    except Exception:
        return patterns

    for item in cache or []:
        client_name = item.get("client_name", "")
        client_id = item.get("client_id")
        last_contact_days = item.get("last_contact_days")
        if last_contact_days is None or not client_name:
            continue

        if last_contact_days <= 3:
            freq, freq_label = "very_active", "very active (contact every few days)"
        elif last_contact_days <= 7:
            freq, freq_label = "active", "active (weekly contact)"
        elif last_contact_days <= 14:
            freq, freq_label = "moderate", "moderate (bi-weekly contact)"
        elif last_contact_days <= 30:
            freq, freq_label = "infrequent", "infrequent (monthly contact)"
        else:
            freq, freq_label = "silent", f"silent ({last_contact_days} days since last contact)"

        entry = {
            "category": "client_intelligence",
            "client_id": client_id,
            "key": "communication_frequency",
            "value": {"frequency": freq, "last_contact_days": last_contact_days, "direction": item.get("last_contact_direction", "unknown")},
            "summary": f"{client_name}: communication is {freq_label}",
            "source": "pattern_detection",
            "confidence": 0.6,
        }
        store.upsert_playbook_entry(user_id, entry)
        patterns.append(entry)

    return patterns
