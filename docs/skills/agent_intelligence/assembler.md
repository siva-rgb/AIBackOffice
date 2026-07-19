# Playbook — Context Assembler Reference

The assembler selects the right Playbook entries for each task, compresses
them into a plain text string under 500 tokens, and returns it for injection
into the LLM prompt. It is a pure function — no LLM calls, no side effects.

---

## Context assembler service

```python
# Add to backend/app/services/playbook.py (same file as observers)

# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT ASSEMBLY — the core of the learning system
# ══════════════════════════════════════════════════════════════════════════════

def assemble_context(
    user_id: str,
    task_type: str,
    client_id: str = None,
    max_chars: int = 1500,   # ~500 tokens at 3 chars/token
) -> str:
    """
    Assemble a plain text Business Context block for LLM prompt injection.

    task_type: "briefing" | "email_draft" | "follow_up_decision" |
               "categorization" | "contract" | "forecast" | "proposal"
    client_id: if the task is client-specific, include client intelligence

    Returns a string to inject into the prompt as:
        BUSINESS CONTEXT (learned from your history):
        {returned string}
    
    Returns empty string if no relevant context exists (day-1 user).
    """
    parts = []

    # ── Tier 1: Identity (always included) ────────────────────────────────
    user = store.get_user(user_id)
    if user:
        profile = user.get("profile") or {}
        identity_parts = []
        if profile.get("business_name"):
            identity_parts.append(profile["business_name"])
        if profile.get("business_type"):
            identity_parts.append(f"({profile['business_type']})")
        if profile.get("industry"):
            identity_parts.append(f"in {profile['industry']}")
        if profile.get("monthly_revenue_goal"):
            identity_parts.append(
                f"Monthly goal: ${profile['monthly_revenue_goal']:,.0f}"
            )
        if identity_parts:
            parts.append(" ".join(identity_parts) + ".")

    # ── Tier 2: Active context from kora_memory (fast cache) ──────────────
    # kora_memory is a compressed rollup written by compress_playbook_to_memory()
    # Use it when available to avoid querying business_playbook on every call
    kora_memory = (user.get("kora_memory") or {}) if user else {}
    used_memory_cache = False

    if kora_memory.get("top_preferences"):
        parts.extend(kora_memory["top_preferences"][:3])
        used_memory_cache = True
    if kora_memory.get("top_rules"):
        parts.extend(kora_memory["top_rules"][:2])
        used_memory_cache = True

    # Fall back to live Playbook query if kora_memory is empty
    if not used_memory_cache:
        preferences = store.get_playbook_entries(
            user_id, category="user_preference", min_confidence=0.6, limit=5
        )
        for pref in preferences:
            if pref.get("summary"):
                parts.append(pref["summary"])

        rules = store.get_playbook_entries(
            user_id, category="business_rule", min_confidence=0.6, limit=3
        )
        for rule in rules:
            if rule.get("summary"):
                parts.append(rule["summary"])

    # Recent corrections (always live query — corrections are critical and change rarely)
    corrections = store.get_playbook_corrections(user_id)
    if corrections:
        correction_summaries = [
            c["summary"] for c in corrections[:5] if c.get("summary")
        ]
        if correction_summaries:
            parts.append("Corrections: " + "; ".join(correction_summaries) + ".")

    # ── Tier 3: Task-specific context ─────────────────────────────────────

    if task_type == "email_draft" and client_id:
        # Include client-specific communication intelligence
        client_entries = store.get_playbook_for_client(user_id, client_id)
        for entry in client_entries[:5]:
            if entry.get("summary"):
                parts.append(entry["summary"])

    elif task_type == "follow_up_decision" and client_id:
        # Include client payment reliability + dismiss history
        client_entries = store.get_playbook_for_client(user_id, client_id)
        payment_entries = [
            e for e in client_entries
            if "payment" in e.get("key", "") or "decision" in e.get("key", "")
        ]
        for entry in payment_entries[:3]:
            if entry.get("summary"):
                parts.append(entry["summary"])
        # Also check for skip rules for this client
        skip_rules = [
            e for e in client_entries
            if e.get("category") == "business_rule" and "skip" in e.get("key", "")
        ]
        for rule in skip_rules[:2]:
            if rule.get("summary"):
                parts.append(rule["summary"])

    elif task_type == "categorization":
        # Corrections already included in Tier 2
        # The bookkeeper should also call apply_corrections_before_llm()
        # separately to short-circuit known patterns
        pass

    elif task_type == "forecast":
        # Include business patterns (seasonality) — critical for accurate forecasts
        if kora_memory.get("top_patterns"):
            parts.extend(kora_memory["top_patterns"][:3])
        else:
            patterns = store.get_playbook_entries(
                user_id, category="business_pattern", min_confidence=0.5, limit=5
            )
            for pattern in patterns:
                if pattern.get("summary"):
                    parts.append(pattern["summary"])

    elif task_type == "contract" or task_type == "proposal":
        # Include user's typical terms + client-specific context
        terms_prefs = store.get_playbook_entries(
            user_id, category="user_preference", min_confidence=0.5, limit=5
        )
        for pref in terms_prefs:
            key = pref.get("key", "")
            if "payment_terms" in key or "brand_tone" in key or "hourly_rate" in key:
                if pref.get("summary"):
                    parts.append(pref["summary"])

        facts = store.get_playbook_entries(
            user_id, category="extracted_fact", min_confidence=0.6, limit=3
        )
        for f in facts:
            key = f.get("key", "")
            if "hourly_rate" in key or "business_type" in key:
                if f.get("summary"):
                    parts.append(f["summary"])

        if client_id:
            client_entries = store.get_playbook_for_client(user_id, client_id)
            for entry in client_entries[:3]:
                if entry.get("summary"):
                    parts.append(entry["summary"])

    elif task_type == "briefing":
        # Include a mix: top patterns + top client intel + extracted facts
        if kora_memory.get("top_patterns"):
            parts.extend(kora_memory["top_patterns"][:3])
        else:
            patterns = store.get_playbook_entries(
                user_id, category="business_pattern", min_confidence=0.5, limit=3
            )
            for p in patterns:
                if p.get("summary"):
                    parts.append(p["summary"])

        if kora_memory.get("top_client_intel"):
            parts.extend(kora_memory["top_client_intel"][:3])
        else:
            client_intel = store.get_playbook_entries(
                user_id, category="client_intelligence", min_confidence=0.6, limit=3
            )
            for ci in client_intel:
                if ci.get("summary"):
                    parts.append(ci["summary"])

        if kora_memory.get("top_facts"):
            parts.extend(kora_memory["top_facts"][:3])
        else:
            facts = store.get_playbook_entries(
                user_id, category="extracted_fact", min_confidence=0.6, limit=3
            )
            for f in facts:
                if f.get("summary"):
                    parts.append(f["summary"])

    # ── Compress to max_chars ─────────────────────────────────────────────
    if not parts:
        return ""

    # Deduplicate
    seen = set()
    unique_parts = []
    for p in parts:
        normalized = p.strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            unique_parts.append(p.strip())

    combined = "\n".join(unique_parts)
    if len(combined) > max_chars:
        # Truncate least important entries (last in list = lowest priority)
        while len(combined) > max_chars and unique_parts:
            unique_parts.pop()
            combined = "\n".join(unique_parts)

    return combined
```

---

## How to inject into existing LLM prompts

Every LLM call that benefits from personalization needs one addition.
The assembler returns empty string for day-1 users → no impact on existing behavior.

### In supervisor.py — compose_manager_briefing()

```python
from app.services.playbook import assemble_context
business_context = assemble_context(user_id, "briefing")

# In the prompt string, add (only if non-empty):
context_section = ""
if business_context:
    context_section = f"\nBUSINESS CONTEXT (learned from your history):\n{business_context}\n"
# Insert before the data snapshot section of the prompt
```

### In butler.py — compose_butler_briefing()

Same pattern:
```python
business_context = assemble_context(user_id, "briefing")
# Add to prompt
```

### In gmail_draft.py — draft_client_reply()

```python
client_id = client["id"]  # already available in this function
business_context = assemble_context(user_id, "email_draft", client_id)
# Add to prompt — this is where email tone + client intel make the biggest difference
```

### In bookkeeper categorization — TWO integration points

**Point 1: Pre-check corrections BEFORE the LLM call** (saves tokens + cost):
```python
from app.services.playbook import apply_corrections_before_llm

# BEFORE calling the LLM to categorize transactions:
# (find the function that sends transactions to the LLM for categorization)
corrected, needs_llm = apply_corrections_before_llm(user_id, transactions)
# corrected: already categorized from corrections (confidence 1.0, skip LLM)
# needs_llm: send these to the LLM as before

# Save corrected ones directly to DB (they don't need the LLM)
for txn in corrected:
    store.update_transaction(user_id, txn["id"], {
        "category": txn["category"],
        "ai_categorized": True,
        "ai_confidence": 1.0,
    })
# Only send needs_llm to the LLM
```

**Point 2: Context injection for the remaining transactions:**
```python
business_context = assemble_context(user_id, "categorization")
# Add corrections as explicit overrides in the categorization prompt
# so the LLM knows the user's preferences for similar transactions
```

### In follow-up agent / supervisor assess()

This is where business rules prevent unnecessary proposals:
```python
from app.services.playbook import assemble_context
from app import store

# Before proposing a follow-up for a client:
def should_propose_followup(user_id: str, invoice: dict, follow_up_stage: str) -> bool:
    client_name = invoice.get("client_name", "")
    # Find client_id by name match
    clients = store.list_clients(user_id)
    client = next((c for c in clients if c.get("name","").lower() == client_name.lower()), None)
    client_id = client["id"] if client else None

    if client_id:
        # Check if user has a skip rule for this client + action type
        client_entries = store.get_playbook_for_client(user_id, client_id)
        for entry in client_entries:
            if entry.get("category") == "business_rule" and "skip" in entry.get("key", ""):
                if entry.get("confidence", 0) >= 0.7:
                    return False  # user consistently dismisses this — don't propose

    return True  # no skip rule found — propose as normal

# In supervisor.assess() or the follow-up logic, call:
# if not should_propose_followup(user_id, invoice, "day_3"):
#     continue  # skip this invoice
```

### In cashflow forecast

```python
business_context = assemble_context(user_id, "forecast")
# Add to the cashflow prompt — seasonality patterns make forecasts much more accurate
# e.g. "Month October had 2.3× average income" tells the LLM to project higher Q4
```

### In contract generation

```python
business_context = assemble_context(user_id, "contract")
# Add to the contract generation prompt
# Injects the user's typical payment terms, hourly rate, revision policy
# so generated contracts match the user's established patterns
```

### In proposal generation

```python
business_context = assemble_context(user_id, "proposal", client_id)
# Add to the proposal prompt
# Injects client-specific intelligence + user's pricing patterns
```

### Pre-check corrections before LLM call (bookkeeper optimization)

For categorization specifically, corrections can short-circuit the LLM entirely:

```python
def apply_corrections_before_llm(user_id: str, transactions: list[dict]) -> tuple[list, list]:
    """
    Check each transaction against correction Playbook entries.
    Returns (already_corrected, needs_llm) — corrected ones skip the LLM call.
    """
    corrections = store.get_playbook_corrections(user_id)
    correction_map = {}
    for c in corrections:
        if c.get("key", "").startswith("category_override_"):
            pattern = c["value"].get("description_pattern", "")
            new_cat = c["value"].get("new_category", "")
            if pattern and new_cat:
                correction_map[pattern] = new_cat

    already_corrected = []
    needs_llm = []

    for txn in transactions:
        desc_key = _normalize_description(txn.get("description", ""))
        if desc_key in correction_map:
            txn["category"] = correction_map[desc_key]
            txn["ai_categorized"] = True
            txn["ai_confidence"] = 1.0  # correction confidence
            already_corrected.append(txn)
        else:
            needs_llm.append(txn)

    return already_corrected, needs_llm
```

---

## Compressed memory (weekly rollup)

```python
def compress_playbook_to_memory(user_id: str) -> dict:
    """
    Roll up the most important Playbook entries into a compact kora_memory
    JSONB on the users table. Called weekly or on demand.
    Returns the compressed memory dict.
    """
    entries = store.get_playbook_entries(
        user_id, min_confidence=0.5, limit=30
    )

    # Group by category
    by_category = {}
    for e in entries:
        cat = e.get("category", "")
        if cat not in by_category:
            by_category[cat] = []
        if e.get("summary"):
            by_category[cat].append(e["summary"])

    memory = {
        "updated_at": datetime.utcnow().isoformat(),
        "total_entries": len(entries),
        "corrections_count": len([e for e in entries if e["category"] == "correction"]),
        "top_preferences": by_category.get("user_preference", [])[:3],
        "top_patterns": by_category.get("business_pattern", [])[:3],
        "top_rules": by_category.get("business_rule", [])[:2],
        "top_client_intel": by_category.get("client_intelligence", [])[:3],
        "top_facts": by_category.get("extracted_fact", [])[:3],
    }

    # Persist to users.kora_memory
    store.update_user(user_id, {"kora_memory": memory})
    return memory
```
