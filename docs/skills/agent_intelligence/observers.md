# Playbook — Observers Reference

Three observer functions that watch user actions and record patterns.
They are synchronous side-effects, not background workers.
Each one is a single function call added to an existing handler.

---

## Observer service

```python
# backend/app/services/playbook.py
"""
Business Playbook — observation, assembly, and pattern detection.
"""
from app import store
from app.services.agent_logger import log_agent_action
from app.models import AgentType
from datetime import datetime


# ══════════════════════════════════════════════════════════════════════════════
# OBSERVER 1: Approve/Dismiss decisions
# ══════════════════════════════════════════════════════════════════════════════

def observe_decision(user_id: str, task: dict, action: str):
    """
    Called after every approve or dismiss on a manager_task.
    Records the pattern so Kora learns what the user wants.

    Wire into: routers/supervisor.py → approve_task() and dismiss_task()
    Add one line: playbook.observe_decision(user_id, task, "approved")
    """
    kind = task.get("kind", "")
    client_id = task.get("payload", {}).get("client_id") or \
                task.get("payload", {}).get("related_client_id")

    # Track per-action-type approval rate
    store.upsert_playbook_entry(user_id, {
        "category": "user_preference",
        "client_id": client_id,
        "key": f"decision_{kind}_{action}",
        "value": {
            "kind": kind,
            "action": action,  # "approved" or "dismissed"
            "task_title": task.get("title", ""),
        },
        "summary": f"User {action} a '{kind}' action" +
                   (f" for client" if client_id else ""),
        "source": "observation",
        "confidence": 0.3,  # low initial; grows with repetition via upsert
    })

    # Detect business rules from repeated dismiss patterns
    # If user dismissed the same kind 3+ times, record a rule
    history = store.get_playbook_entries(
        user_id,
        category="user_preference",
        client_id=client_id,
    )
    dismiss_count = sum(
        1 for e in history
        if e.get("key", "").startswith(f"decision_{kind}_dismissed")
        and e.get("observation_count", 0) >= 3
    )
    if dismiss_count > 0 and action == "dismissed":
        rule_key = f"skip_{kind}" + (f"_client_{client_id}" if client_id else "")
        store.upsert_playbook_entry(user_id, {
            "category": "business_rule",
            "client_id": client_id,
            "key": rule_key,
            "value": {"kind": kind, "reason": "repeatedly dismissed"},
            "summary": f"User consistently dismisses '{kind}' actions" +
                       (f" for this client" if client_id else "") +
                       " — consider not proposing",
            "source": "observation",
            "confidence": 0.7,
        })


# ══════════════════════════════════════════════════════════════════════════════
# OBSERVER 2: Category corrections (bookkeeping)
# ══════════════════════════════════════════════════════════════════════════════

def observe_correction(
    user_id: str,
    transaction_id: str,
    description: str,
    old_category: str,
    new_category: str,
):
    """
    Called when user manually changes a transaction category.
    Stores as a permanent correction (confidence 1.0, never decays).

    Wire into: the route/handler that updates transaction category.
    If no dedicated route exists yet, wire into wherever the frontend
    PATCHes a transaction's category field.
    """
    if old_category == new_category:
        return  # no actual change

    # Extract a normalized description key (the merchant/vendor name)
    # e.g. "ADOBE SYSTEMS *CREATIVECLOUD" → "adobe systems"
    desc_key = _normalize_description(description)

    store.upsert_playbook_entry(user_id, {
        "category": "correction",
        "client_id": None,  # corrections are global, not per-client
        "key": f"category_override_{desc_key}",
        "value": {
            "description_pattern": desc_key,
            "original_description": description,
            "old_category": old_category,
            "new_category": new_category,
        },
        "summary": f'"{desc_key}" should be categorized as {new_category} (user corrected from {old_category})',
        "source": "correction",
        "confidence": 1.0,  # corrections are always authoritative
    })

    try:
        log_agent_action(
            user_id=user_id,
            agent_type=AgentType.playbook,
            action=f"Recorded category correction: {desc_key} → {new_category}",
            input_data={"transaction_id": transaction_id, "old": old_category},
            output_data={"new": new_category},
            latency_ms=0,
            triggered_by="user",
        )
    except Exception:
        pass  # logging failure should never block the correction


def _normalize_description(desc: str) -> str:
    """Normalize a transaction description to a matchable key."""
    import re
    clean = desc.upper().strip()
    # Remove common noise: transaction IDs, dates, asterisks
    clean = re.sub(r'[*#]\S+', '', clean)
    clean = re.sub(r'\d{4,}', '', clean)  # remove long number sequences
    clean = re.sub(r'\s+', ' ', clean).strip()
    # Take first 2-3 words as the key (the merchant name)
    words = clean.split()[:3]
    return " ".join(words).lower()


# ══════════════════════════════════════════════════════════════════════════════
# OBSERVER 3: Email draft edits
# ══════════════════════════════════════════════════════════════════════════════

def observe_email_edit(
    user_id: str,
    original_body: str,
    edited_body: str,
    client_id: str = None,
):
    """
    Called when user edits an email draft before approving.
    Extracts tone/style signals from the diff.

    Wire into: the approve handler for 'send_email_gmail' tasks,
    IF the payload contains an edited body that differs from the original.
    """
    if not original_body or not edited_body:
        return
    if original_body.strip() == edited_body.strip():
        return  # no edit made

    # Simple heuristic signals (no LLM call needed)
    signals = {}

    # Length preference
    orig_words = len(original_body.split())
    edit_words = len(edited_body.split())
    if edit_words < orig_words * 0.7:
        signals["length_preference"] = "shorter"
    elif edit_words > orig_words * 1.3:
        signals["length_preference"] = "longer"

    # Formality signals
    informal_markers = ["hey", "hi ", "thanks!", "cheers", "lol", "haha"]
    formal_markers = ["dear", "regards", "sincerely", "respectfully"]
    edit_lower = edited_body.lower()
    has_informal = any(m in edit_lower for m in informal_markers)
    has_formal = any(m in edit_lower for m in formal_markers)
    if has_informal and not has_formal:
        signals["tone"] = "casual"
    elif has_formal and not has_informal:
        signals["tone"] = "formal"

    # Greeting pattern
    first_line = edited_body.strip().split("\n")[0].strip()
    if first_line.lower().startswith("hi "):
        signals["greeting_style"] = "hi_firstname"
    elif first_line.lower().startswith("hey "):
        signals["greeting_style"] = "hey_firstname"
    elif first_line.lower().startswith("dear "):
        signals["greeting_style"] = "dear_firstname"

    if not signals:
        return  # nothing clear to learn

    store.upsert_playbook_entry(user_id, {
        "category": "user_preference",
        "client_id": client_id,
        "key": "email_style" + (f"_client_{client_id}" if client_id else ""),
        "value": signals,
        "summary": _build_style_summary(signals),
        "source": "observation",
        "confidence": 0.4,  # grows with repeated edits
    })


def _build_style_summary(signals: dict) -> str:
    parts = []
    if "length_preference" in signals:
        parts.append(f"prefers {signals['length_preference']} emails")
    if "tone" in signals:
        parts.append(f"{signals['tone']} tone")
    if "greeting_style" in signals:
        parts.append(f"opens with '{signals['greeting_style'].replace('_', ' ')}'")
    return "User " + ", ".join(parts) if parts else ""


# ══════════════════════════════════════════════════════════════════════════════
# OBSERVER 4: Payment reconciliation → client payment speed
# ══════════════════════════════════════════════════════════════════════════════

def observe_payment(user_id: str, invoice: dict, transaction: dict):
    """
    Called when cross_module.reconcile_payments() matches a payment to an invoice.
    Records the client's payment speed as client_intelligence.

    Wire into: services/cross_module.py → reconcile_payments()
    After the invoice is marked paid, add:
      playbook.observe_payment(user_id, invoice, matched_transaction)
    """
    client_name = invoice.get("client_name", "")
    if not client_name:
        return

    # Calculate payment speed (days from due_date to payment)
    due_date = invoice.get("due_date")
    payment_date = transaction.get("date")
    days_to_pay = None
    if due_date and payment_date:
        try:
            from datetime import datetime as dt
            due = dt.fromisoformat(str(due_date).replace("Z", "+00:00")).date()
            paid = dt.fromisoformat(str(payment_date).replace("Z", "+00:00")).date()
            days_to_pay = (paid - due).days  # negative = paid early, positive = late
        except Exception:
            pass

    # Match to client record by name
    clients = store.list_clients(user_id)
    matched = next(
        (c for c in clients if c.get("name", "").lower() == client_name.lower()),
        None
    )
    client_id = matched["id"] if matched else None

    speed_label = "early" if days_to_pay and days_to_pay < 0 else \
                  "on_time" if days_to_pay is not None and days_to_pay <= 3 else \
                  "late" if days_to_pay is not None else "unknown"

    store.upsert_playbook_entry(user_id, {
        "category": "client_intelligence",
        "client_id": client_id,
        "key": "payment_speed",
        "value": {
            "client_name": client_name,
            "days_to_pay": days_to_pay,
            "speed": speed_label,
            "invoice_amount": invoice.get("total"),
            "follow_up_count": invoice.get("follow_up_count", 0),
        },
        "summary": f"{client_name} paid {'early' if speed_label == 'early' else f'{days_to_pay} days after due date'}"
                   + (f" after {invoice.get('follow_up_count', 0)} reminder(s)" if invoice.get("follow_up_count") else ""),
        "source": "observation",
        "confidence": 0.5,  # grows with each observed payment
    })


# ══════════════════════════════════════════════════════════════════════════════
# OBSERVER 5: Gmail intel → Playbook bridge (Phase 2)
# ══════════════════════════════════════════════════════════════════════════════

def observe_email_intel(user_id: str, client_id: str, intel: dict):
    """
    Called after gmail_intel.py processes a client's email threads.
    Bridges email_intel_cache data into the Playbook as extracted_facts
    and client_intelligence entries.

    Wire into: services/gmail_intel.py → _analyze_threads()
    After intel is computed and cached, add:
      playbook.observe_email_intel(user_id, client_id, intel)
    """
    client_name = intel.get("client_name", "")

    # Extract financial mentions as facts
    for mention in intel.get("financial_mentions", []):
        if mention.get("amount") and mention.get("type"):
            store.upsert_playbook_entry(user_id, {
                "category": "extracted_fact",
                "client_id": client_id,
                "key": f"financial_mention_{mention['type']}",
                "value": mention,
                "summary": f"{client_name}: {mention['type']} of ${mention['amount']:,.0f} mentioned in email"
                           if mention.get("amount") else f"{client_name}: {mention.get('context', '')}",
                "source": "extraction",
                "confidence": 0.6,
            })

    # Extract commitments as facts
    for commitment in intel.get("commitments_pending", []):
        who = commitment.get("who", "")
        what = commitment.get("what", "")
        if what:
            store.upsert_playbook_entry(user_id, {
                "category": "extracted_fact",
                "client_id": client_id,
                "key": f"commitment_{who}",
                "value": commitment,
                "summary": f"{client_name}: {who} committed to '{what}'"
                           + (f" by {commitment['mentioned_date']}" if commitment.get("mentioned_date") else ""),
                "source": "extraction",
                "confidence": 0.55,
            })

    # Record relationship health as client intelligence
    if intel.get("relationship_health") and intel["relationship_health"] != "unknown":
        store.upsert_playbook_entry(user_id, {
            "category": "client_intelligence",
            "client_id": client_id,
            "key": "email_relationship_health",
            "value": {
                "health": intel["relationship_health"],
                "sentiment": intel.get("sentiment"),
                "last_contact_days": intel.get("last_contact_days"),
            },
            "summary": f"{client_name}: email relationship is {intel['relationship_health']}"
                       + (f" (sentiment: {intel['sentiment']})" if intel.get("sentiment") else ""),
            "source": "extraction",
            "confidence": 0.6,
        })


# ══════════════════════════════════════════════════════════════════════════════
# OBSERVER 6: Meeting agent → Playbook bridge (Phase 2)
# ══════════════════════════════════════════════════════════════════════════════

def observe_meeting(user_id: str, client_id: str, extracted: dict):
    """
    Called after meeting_agent.py extracts MOM from a transcript.
    Bridges decisions and commitments into the Playbook as extracted_facts.

    Wire into: services/meeting_agent.py → process_transcript()
    After extracted data is stored in the meetings table, add:
      playbook.observe_meeting(user_id, client_id, extracted)
    """
    if not client_id:
        return

    # Extract financial commitments
    for mention in extracted.get("financial_mentions", []):
        if mention.get("amount"):
            store.upsert_playbook_entry(user_id, {
                "category": "extracted_fact",
                "client_id": client_id,
                "key": f"meeting_financial_{mention.get('type', 'unknown')}",
                "value": mention,
                "summary": f"Meeting mentioned: {mention.get('type', '')} ${mention['amount']:,.0f}"
                           + (f" — {mention.get('context', '')}" if mention.get("context") else ""),
                "source": "extraction",
                "confidence": 0.65,
            })

    # Extract client commitments (things the client promised)
    for commitment in extracted.get("commitments", []):
        if commitment.get("who") == "client" and commitment.get("what"):
            store.upsert_playbook_entry(user_id, {
                "category": "extracted_fact",
                "client_id": client_id,
                "key": "client_commitment",
                "value": commitment,
                "summary": f"Client committed: {commitment['what']}"
                           + (f" by {commitment['by_when']}" if commitment.get("by_when") else ""),
                "source": "extraction",
                "confidence": 0.7,
            })


# ══════════════════════════════════════════════════════════════════════════════
# OBSERVER 7: Onboarding → Playbook seed
# ══════════════════════════════════════════════════════════════════════════════

def seed_from_onboarding(user_id: str, profile: dict):
    """
    Called when user completes onboarding. Seeds the Playbook with initial
    business context so the first briefing has something to work with.

    Wire into: the handler that sets onboarding_completed = true.
    After updating the user, add:
      playbook.seed_from_onboarding(user_id, profile_data)
    """
    if not profile:
        return

    # Business type
    if profile.get("business_type"):
        store.upsert_playbook_entry(user_id, {
            "category": "extracted_fact",
            "client_id": None,
            "key": "business_type",
            "value": {"type": profile["business_type"]},
            "summary": f"Business type: {profile['business_type']}",
            "source": "onboarding",
            "confidence": 1.0,
        })

    # Industry
    if profile.get("industry"):
        store.upsert_playbook_entry(user_id, {
            "category": "extracted_fact",
            "client_id": None,
            "key": "industry",
            "value": {"industry": profile["industry"]},
            "summary": f"Industry: {profile['industry']}",
            "source": "onboarding",
            "confidence": 1.0,
        })

    # Revenue goal
    if profile.get("monthly_revenue_goal"):
        store.upsert_playbook_entry(user_id, {
            "category": "business_pattern",
            "client_id": None,
            "key": "monthly_revenue_goal",
            "value": {"goal": profile["monthly_revenue_goal"]},
            "summary": f"Monthly revenue goal: ${profile['monthly_revenue_goal']:,.0f}",
            "source": "onboarding",
            "confidence": 1.0,
        })

    # Payment preferences
    if profile.get("default_payment_terms"):
        store.upsert_playbook_entry(user_id, {
            "category": "user_preference",
            "client_id": None,
            "key": "default_payment_terms",
            "value": {"terms": profile["default_payment_terms"]},
            "summary": f"Default payment terms: {profile['default_payment_terms']}",
            "source": "onboarding",
            "confidence": 0.9,
        })

    # Hourly rate
    if profile.get("hourly_rate"):
        store.upsert_playbook_entry(user_id, {
            "category": "extracted_fact",
            "client_id": None,
            "key": "hourly_rate",
            "value": {"rate": profile["hourly_rate"], "currency": profile.get("currency", "USD")},
            "summary": f"Standard hourly rate: ${profile['hourly_rate']}/hour",
            "source": "onboarding",
            "confidence": 0.9,
        })

    # Brand tone
    if profile.get("brand_tone"):
        store.upsert_playbook_entry(user_id, {
            "category": "user_preference",
            "client_id": None,
            "key": "brand_tone",
            "value": {"tone": profile["brand_tone"]},
            "summary": f"Communication tone: {profile['brand_tone']}",
            "source": "onboarding",
            "confidence": 0.9,
        })


# ══════════════════════════════════════════════════════════════════════════════
# PATTERN DETECTION (runs on demand, not scheduled)
# ══════════════════════════════════════════════════════════════════════════════

def detect_patterns(user_id: str) -> list[dict]:
    """
    Analyze transaction history and client data for patterns.
    Called via POST /api/playbook/detect or weekly via button.
    Returns list of newly detected patterns.
    """
    detected = []

    # 1. Client payment reliability
    detected.extend(_detect_client_payment_patterns(user_id))

    # 2. Income seasonality
    detected.extend(_detect_income_seasonality(user_id))

    # 3. Billing rhythm
    detected.extend(_detect_billing_rhythm(user_id))

    # 4. Communication frequency per client
    detected.extend(_detect_communication_frequency(user_id))

    return detected


def _detect_client_payment_patterns(user_id: str) -> list[dict]:
    """Analyze invoice payment history per client."""
    patterns = []
    invoices = store.list_invoices(user_id)
    if not invoices:
        return patterns

    # Group by client_name
    from collections import defaultdict
    by_client = defaultdict(list)
    for inv in invoices:
        name = inv.get("client_name", "")
        if name:
            by_client[name.lower()].append(inv)

    for client_name_lower, client_invoices in by_client.items():
        paid = [i for i in client_invoices if i.get("status") == "paid"]
        overdue = [i for i in client_invoices if i.get("status") == "overdue"]
        total = len(client_invoices)

        if total < 3:
            continue  # not enough data

        # Payment reliability
        paid_pct = len(paid) / total if total > 0 else 0
        reliability = "reliable" if paid_pct > 0.8 else "mixed" if paid_pct > 0.5 else "unreliable"

        # Try to match to a client record
        clients = store.list_clients(user_id)
        matched_client = next(
            (c for c in clients if c.get("name", "").lower() == client_name_lower),
            None
        )
        client_id = matched_client["id"] if matched_client else None

        entry = {
            "category": "client_intelligence",
            "client_id": client_id,
            "key": f"payment_reliability",
            "value": {
                "reliability": reliability,
                "paid_count": len(paid),
                "overdue_count": len(overdue),
                "total_invoices": total,
                "paid_percentage": round(paid_pct * 100),
            },
            "summary": f"Payment reliability: {reliability} ({round(paid_pct*100)}% paid on time, {total} invoices)",
            "source": "pattern_detection",
            "confidence": min(0.9, 0.5 + (total * 0.05)),
        }
        store.upsert_playbook_entry(user_id, entry)
        patterns.append(entry)

    return patterns


def _detect_income_seasonality(user_id: str) -> list[dict]:
    """Detect monthly income patterns from transaction history."""
    patterns = []
    transactions = store.list_transactions(user_id)
    if not transactions:
        return patterns

    # Group income by month
    from collections import defaultdict
    monthly_income = defaultdict(float)
    for txn in transactions:
        if txn.get("type") == "income" and txn.get("date"):
            month_key = txn["date"][:7]  # "2026-01"
            monthly_income[month_key] += abs(txn.get("amount", 0))

    if len(monthly_income) < 3:
        return patterns  # need at least 3 months

    values = list(monthly_income.values())
    avg = sum(values) / len(values)
    if avg == 0:
        return patterns

    # Find months significantly above or below average
    for month, income in monthly_income.items():
        ratio = income / avg
        if ratio > 1.5:
            entry = {
                "category": "business_pattern",
                "client_id": None,
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
    """Detect when invoices are typically created (day of week / day of month)."""
    patterns = []
    invoices = store.list_invoices(user_id)
    if len(invoices) < 5:
        return patterns

    from collections import Counter
    from datetime import datetime as dt

    days_of_month = Counter()
    for inv in invoices:
        created = inv.get("created_at", "")
        if created:
            try:
                day = dt.fromisoformat(created.replace("Z", "+00:00")).day
                days_of_month[day] += 1
            except Exception:
                pass

    if not days_of_month:
        return patterns

    most_common_day, count = days_of_month.most_common(1)[0]
    if count >= 3:
        entry = {
            "category": "business_pattern",
            "client_id": None,
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
    """Detect per-client communication frequency from email_intel_cache."""
    patterns = []
    try:
        # Read from email_intel_cache (populated by gmail_intel.py)
        cache = store.get_email_intel_cache(user_id) if hasattr(store, 'get_email_intel_cache') else []
    except Exception:
        cache = []

    if not cache:
        return patterns

    for entry in cache:
        client_name = entry.get("client_name", "")
        client_id = entry.get("client_id")
        last_contact_days = entry.get("last_contact_days")

        if last_contact_days is None or not client_name:
            continue

        # Determine communication frequency label
        if last_contact_days <= 3:
            freq = "very_active"
            freq_label = "very active (contact every few days)"
        elif last_contact_days <= 7:
            freq = "active"
            freq_label = "active (weekly contact)"
        elif last_contact_days <= 14:
            freq = "moderate"
            freq_label = "moderate (bi-weekly contact)"
        elif last_contact_days <= 30:
            freq = "infrequent"
            freq_label = "infrequent (monthly contact)"
        else:
            freq = "silent"
            freq_label = f"silent ({last_contact_days} days since last contact)"

        pattern = {
            "category": "client_intelligence",
            "client_id": client_id,
            "key": "communication_frequency",
            "value": {
                "frequency": freq,
                "last_contact_days": last_contact_days,
                "direction": entry.get("last_contact_direction", "unknown"),
            },
            "summary": f"{client_name}: communication is {freq_label}",
            "source": "pattern_detection",
            "confidence": 0.6,
        }
        store.upsert_playbook_entry(user_id, pattern)
        patterns.append(pattern)

    return patterns
```

---

## Where to wire each observer

### Observer 1 — Approve/Dismiss

In `routers/supervisor.py`, find the approve and dismiss handlers:

```python
# In the approve handler, after the task is marked 'done':
from app.services.playbook import observe_decision
observe_decision(user_id, task, "approved")

# In the dismiss handler, after the task is marked 'dismissed':
observe_decision(user_id, task, "dismissed")
```

### Observer 2 — Category correction

If a PATCH route for transaction category exists, add there.
If not, add a new route or wire into wherever the frontend updates a category:

```python
# After updating the transaction category in DB:
from app.services.playbook import observe_correction
observe_correction(
    user_id=user_id,
    transaction_id=txn_id,
    description=txn["description"],
    old_category=old_category,
    new_category=new_category,
)
```

### Observer 3 — Email draft edit

In the approve handler for `send_email_gmail` tasks, check if the body was edited:

```python
# In supervisor.approve_task(), when kind == "send_email_gmail":
original_body = task["payload"].get("body_text", "")
# If the frontend sent an edited body in the approve request:
edited_body = approve_request.get("edited_body", original_body)
if edited_body != original_body:
    from app.services.playbook import observe_email_edit
    observe_email_edit(
        user_id=user_id,
        original_body=original_body,
        edited_body=edited_body,
        client_id=task["payload"].get("related_client_id"),
    )
```

### Observer 4 — Payment reconciliation

In `services/cross_module.py`, inside `reconcile_payments()`, after marking an invoice paid:

```python
from app.services.playbook import observe_payment
# After: store.update_invoice(user_id, invoice_id, {"status": "paid", ...})
observe_payment(user_id, invoice, matched_transaction)
```

### Observer 5 — Gmail intel bridge (Phase 2)

In `services/gmail_intel.py`, after `_analyze_threads()` returns and cache is written:

```python
from app.services.playbook import observe_email_intel
# After: db.table("email_intel_cache").upsert({...})
observe_email_intel(user_id, client_id, intel)
```

### Observer 6 — Meeting agent bridge (Phase 2)

In `services/meeting_agent.py`, after MOM extraction succeeds:

```python
from app.services.playbook import observe_meeting
# After: db.table("meetings").update({...parsed data...})
if client_id:
    observe_meeting(user_id, client_id, extracted)
```

### Observer 7 — Onboarding seed

In whatever handler sets `onboarding_completed = true` (likely in `routers/users.py`
or the onboarding completion endpoint):

```python
from app.services.playbook import seed_from_onboarding
# After: store.update_user(user_id, {"onboarding_completed": True})
user = store.get_user(user_id)
profile = user.get("profile") or {}
seed_from_onboarding(user_id, profile)
```
