# Playbook — Validation Reference

Post-LLM output validation. Catches hallucinated numbers and unknown entities.
Runs after every structured LLM output (briefings, email drafts) before reaching the user.

---

## Validation service

```python
# backend/app/services/validation.py
"""
Post-LLM output validation for hallucination prevention.
Thin, fast, no LLM calls. Checks output against source data.
"""
import re
from app.services.agent_logger import log_agent_action
from app.models import AgentType


def validate_briefing(
    briefing: dict,
    source_state: dict,
    user_id: str,
) -> dict:
    """
    Validate a manager or butler briefing against the source data that was
    provided to the LLM. Catches hallucinated dollar amounts and unknown names.

    Returns the briefing dict (possibly cleaned). Logs any issues found.
    """
    issues = []

    # ── Check 1: dollar amounts in output must exist in source ────────────
    known_amounts = _extract_known_amounts(source_state)
    output_text = _flatten_briefing_text(briefing)
    output_amounts = _extract_dollar_amounts(output_text)

    for amount in output_amounts:
        if amount not in known_amounts:
            issues.append(f"Unverified amount: ${amount:,.0f} (not in source data)")

    # ── Check 2: client names in output must be in the known list ─────────
    known_names = set()
    for client in source_state.get("clients", []):
        name = client.get("name", "")
        if name:
            known_names.add(name.lower())
    # Also add client_name from invoices/overdue lists
    for inv in source_state.get("overdue_invoices", []):
        name = inv.get("client_name", "")
        if name:
            known_names.add(name.lower())

    # Simple check: look for capitalized multi-word phrases that could be names
    # This is imperfect but catches the most obvious hallucinations
    potential_names = re.findall(r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b', output_text)
    for name in potential_names:
        if name.lower() not in known_names:
            # Could be a generic phrase like "Cash Flow" — check if it looks like a name
            generic_phrases = {
                "cash flow", "net profit", "monthly goal", "payment demand",
                "follow up", "action items", "next steps", "business manager",
                "morning briefing", "approval queue",
            }
            if name.lower() not in generic_phrases:
                issues.append(f"Unknown name: '{name}' (not a known client)")

    # ── Log issues but don't block ────────────────────────────────────────
    if issues:
        try:
            log_agent_action(
                user_id=user_id,
                agent_type=AgentType.playbook,
                action="Validation flagged potential hallucination",
                input_data={"issue_count": len(issues)},
                output_data={"issues": issues[:5]},  # cap at 5 to avoid bloat
                latency_ms=0,
                triggered_by="system",
            )
        except Exception:
            pass

    # Attach validation metadata to the briefing
    briefing["_validation"] = {
        "checked": True,
        "issues": issues,
        "passed": len(issues) == 0,
    }

    return briefing


def validate_email_draft(
    draft: dict,
    client_name: str,
    known_amounts: list[float],
    user_id: str,
) -> dict:
    """
    Validate an AI-drafted email before it enters the approval queue.
    """
    issues = []
    body = draft.get("body_text", "") or draft.get("body_html", "")

    # Check amounts
    amounts_in_body = _extract_dollar_amounts(body)
    for amount in amounts_in_body:
        if amount not in known_amounts and amount not in {a * 0.5 for a in known_amounts}:
            issues.append(f"Unverified amount in email: ${amount:,.0f}")

    # Check that the email addresses the right client
    if client_name and client_name.lower() not in body.lower():
        # Not necessarily an issue — could use first name only
        first_name = client_name.split()[0] if client_name else ""
        if first_name and first_name.lower() not in body.lower():
            issues.append(f"Email doesn't mention client name: {client_name}")

    if issues:
        try:
            log_agent_action(
                user_id=user_id,
                agent_type=AgentType.playbook,
                action="Email draft validation flagged issues",
                input_data={"client": client_name},
                output_data={"issues": issues},
                latency_ms=0,
                triggered_by="system",
            )
        except Exception:
            pass

    draft["_validation"] = {
        "checked": True,
        "issues": issues,
        "passed": len(issues) == 0,
    }
    return draft


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_known_amounts(source_state: dict) -> set[float]:
    """Extract all dollar amounts from the source data that the LLM was given."""
    amounts = set()

    # Direct numeric fields
    for key in ["overdue_total", "income_30d", "monthly_goal", "projected_balance"]:
        val = source_state.get(key)
        if val is not None and val != 0:
            amounts.add(float(val))

    # Amounts from invoices
    for inv in source_state.get("overdue_invoices", []):
        total = inv.get("total")
        if total:
            amounts.add(float(total))

    # Common derived amounts (sums, differences)
    if "income_30d" in source_state and "monthly_goal" in source_state:
        gap = source_state["monthly_goal"] - source_state["income_30d"]
        if gap > 0:
            amounts.add(float(gap))

    return amounts


def _extract_dollar_amounts(text: str) -> list[float]:
    """Extract dollar amounts from text. Returns list of floats."""
    # Match patterns like $3,200 or $3200 or $3,200.00 or ₹8,00,000
    pattern = r'[\$₹£€]\s?([\d,]+(?:\.\d{1,2})?)'
    matches = re.findall(pattern, text)
    amounts = []
    for m in matches:
        try:
            clean = m.replace(",", "")
            amounts.append(float(clean))
        except ValueError:
            pass
    return amounts


def _flatten_briefing_text(briefing: dict) -> str:
    """Concatenate all text fields from a briefing dict."""
    texts = []
    for key in ["headline", "two_sentence_summary", "key_insight",
                 "going_well", "watch_out"]:
        val = briefing.get(key)
        if val and isinstance(val, str):
            texts.append(val)
    focus = briefing.get("focus_today", [])
    if isinstance(focus, list):
        texts.extend(str(f) for f in focus)
    return " ".join(texts)
```

---

## Where to wire validation

### In supervisor.py — after compose_manager_briefing()

```python
from app.services.validation import validate_briefing

# After the LLM returns the briefing JSON:
briefing = validate_briefing(briefing, state, user_id)
# state = the dict that was passed to the LLM prompt
# validation issues are logged automatically; briefing still returns to user
```

### In butler.py — after compose_butler_briefing()

Same pattern:
```python
briefing = validate_briefing(briefing, state, user_id)
```

### In gmail_draft.py — after generating an email draft

```python
from app.services.validation import validate_email_draft

# Get known amounts from the client's invoices
client_invoices = store.list_invoices(user_id)
client_amounts = [inv["total"] for inv in client_invoices if inv.get("total")]

draft = validate_email_draft(draft, client_name, client_amounts, user_id)
```
