from __future__ import annotations

import re

from . import agent_logger
from ..models import AgentType


def validate_briefing(briefing: dict, source_state: dict, user_id: str) -> dict:
    if not isinstance(briefing, dict):
        return briefing

    text = _flatten_briefing_text(briefing)
    issues: list[str] = []

    known_amounts = _extract_known_amounts(source_state)
    if known_amounts:
        for amount in _extract_dollar_amounts(text):
            if not any(abs(amount - k) / max(k, 1) < 0.05 for k in known_amounts):
                issues.append(f"Amount {amount} not found in source data")

    known_clients: set[str] = set()
    clients_list = source_state.get("clients") or source_state.get("client_list") or []
    for c in clients_list:
        name = c.get("name") or c.get("client_name") or ""
        if name:
            known_clients.add(name.lower())
    if known_clients:
        for phrase in re.findall(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)\b", text):
            if phrase.lower() not in known_clients:
                issues.append(f"Unknown entity '{phrase}' in briefing")

    issues = issues[:5]
    if issues:
        try:
            agent_logger.log_action(
                user_id=user_id,
                agent_type=AgentType.playbook,
                action="Validation flagged potential hallucination",
                input={"issues": issues},
                output={"briefingKeys": list(briefing.keys())},
                triggered_by="validation",
            )
        except Exception:
            pass

    briefing["_validation"] = {
        "checked": True,
        "issues": issues,
        "passed": len(issues) == 0,
    }
    return briefing


def validate_email_draft(draft: dict, client_name: str, known_amounts: list[float], user_id: str) -> dict:
    if not isinstance(draft, dict):
        return draft

    body = draft.get("body") or draft.get("body_text") or draft.get("content") or ""
    issues: list[str] = []

    if known_amounts and body:
        for amount in _extract_dollar_amounts(body):
            halved = [k * 0.5 for k in known_amounts]
            all_valid = set(known_amounts) | set(halved)
            if not any(abs(amount - k) / max(k, 1) < 0.05 for k in all_valid):
                issues.append(f"Amount {amount} not in known client amounts")

    if client_name and body:
        first_name = client_name.split()[0] if client_name.split() else client_name
        if client_name.lower() not in body.lower() and first_name.lower() not in body.lower():
            issues.append(f"Email does not mention client '{client_name}'")

    issues = issues[:5]
    if issues:
        try:
            agent_logger.log_action(
                user_id=user_id,
                agent_type=AgentType.playbook,
                action="Email draft validation flagged issues",
                input={"clientName": client_name, "issues": issues},
                output={"bodyLength": len(body)},
                triggered_by="validation",
            )
        except Exception:
            pass

    draft["_validation"] = {
        "checked": True,
        "issues": issues,
        "passed": len(issues) == 0,
    }
    return draft


def _extract_known_amounts(source_state: dict) -> set[float]:
    amounts: set[float] = set()
    for key in ("overdue_total", "income_30d", "monthly_goal", "projected_balance", "current_balance"):
        val = source_state.get(key)
        if isinstance(val, (int, float)) and val > 0:
            amounts.add(float(val))
    income = source_state.get("income_30d") or source_state.get("month_income") or 0
    goal = source_state.get("monthly_goal") or source_state.get("monthly_revenue_goal") or 0
    gap = float(goal) - float(income)
    if gap > 0:
        amounts.add(round(gap, 2))
    for inv in source_state.get("overdue_invoices", []) or source_state.get("overdue", []):
        total = inv.get("total") if isinstance(inv, dict) else getattr(inv, "total", None)
        if total and float(total) > 0:
            amounts.add(float(total))
    return amounts


def _extract_dollar_amounts(text: str) -> list[float]:
    matches = re.findall(r"[\$₹£€]\s?([\d,]+(?:\.\d{1,2})?)", text)
    result = []
    for m in matches:
        try:
            result.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return result


def _flatten_briefing_text(briefing: dict) -> str:
    parts = []
    for key in ("headline", "two_sentence_summary", "twoSentenceSummary", "key_insight", "keyInsight", "going_well", "goingWell", "watch_out", "watchOut"):
        val = briefing.get(key)
        if val and isinstance(val, str):
            parts.append(val)
    for item in briefing.get("focus_today", []) or briefing.get("focusToday", []):
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(item.get("text") or item.get("title") or "")
    return " ".join(parts)
