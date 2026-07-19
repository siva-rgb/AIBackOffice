from __future__ import annotations

from datetime import datetime, timezone

from .. import store
from ..models import (
    Contract,
    ContractReview,
    Engagement,
    GenerateContractRequest,
    ReviewFinding,
    User,
)
from ..utils.security import safe_sanitize
from . import agent_logger, storage
from .vertex_ai import generate_with_retry, get_ai

_MAX_REVIEW_CHARS = 60_000
_SEVERITIES = {"high", "medium", "low"}

_TITLES = {
    "nda": "Non-Disclosure Agreement",
    "freelance_agreement": "Freelance Agreement",
    "service_contract": "Service Contract",
    "refund_policy": "Refund Policy",
    "ip_transfer": "IP Assignment Agreement",
}


def _sanitize_terms(terms: dict) -> dict:
    clean = {}
    for k, v in terms.items():
        clean[k] = safe_sanitize(v) if isinstance(v, str) else v
    return clean


def generate_contract(user: User, req: GenerateContractRequest) -> Contract:
    """Generate an AI contract (SKILL.md §5), persist it, and log the action."""
    ai = get_ai()
    payload = {
        "type": req.type,
        "client_name": safe_sanitize(req.client_name),
        "provider_name": req.provider_name or user.business_name or user.full_name or "Service Provider",
        "jurisdiction": req.jurisdiction,
        "terms": _sanitize_terms(req.terms),
    }
    try:
        from .playbook import assemble_context
        business_context = assemble_context(user.id, "contract")
        if business_context:
            payload["business_context"] = business_context
    except Exception:
        pass
    call = generate_with_retry(lambda: ai.generate_contract(payload))
    content_md = call.data.get("content_md")

    # Auto-review the freshly drafted contract so the owner immediately sees any
    # risky/missing clauses. Embedded in terms._review (camelCase) so it persists
    # and round-trips without a schema change. Best-effort — never blocks drafting.
    terms = dict(req.terms or {})
    if content_md:
        try:
            review = review_contract(user, text=content_md, source="kora",
                                     title=f"{_TITLES.get(req.type, 'Agreement')} — {req.client_name}")
            terms["_review"] = review.model_dump(by_alias=True)
        except Exception as exc:
            print(f"[contract] auto-review skipped: {exc}")

    contract = Contract(
        id=store.uid("ctr"),
        user_id=user.id,
        type=req.type,
        title=f"{_TITLES.get(req.type, 'Agreement')} — {req.client_name}",
        client_name=req.client_name,
        client_email=req.client_email,
        provider_name=payload["provider_name"],
        jurisdiction=req.jurisdiction,
        terms=terms,
        content_md=content_md,
        section_explanations=call.data.get("section_explanations", {}),
        status="draft",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    store.insert_contract(contract)

    agent_logger.log_action(
        user_id=user.id,
        agent_type="contract_generator",
        action=f"Generated {_TITLES.get(req.type, 'contract')} for {req.client_name} ({req.jurisdiction})",
        input={"type": req.type, "jurisdiction": req.jurisdiction, "terms": req.terms},
        output={"contractId": contract.id, "sections": list((contract.section_explanations or {}).keys())},
        model_used=call.model_used,
        tokens_used=call.tokens_used,
        latency_ms=call.latency_ms,
        cost_usd=call.cost_usd,
        triggered_by="user",
        source_record_type="contract",
        source_record_id=contract.id,
    )
    return contract


# --- Contract review --------------------------------------------------------
def _as_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, dict):  # tolerate the model returning objects
            out.append("; ".join(f"{k}: {x}" for k, x in v.items() if x))
    return out


def _normalize_review(data: dict, *, source: str, title: str | None) -> ContractReview:
    """Coerce the (non-deterministic) model output into a safe ContractReview."""
    risk = str(data.get("overall_risk", "medium")).lower()
    if risk not in _SEVERITIES:
        risk = "medium"

    findings: list[ReviewFinding] = []
    for f in data.get("findings", []) or []:
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "medium")).lower()
        if sev not in _SEVERITIES:
            sev = "medium"
        issue = str(f.get("issue") or f.get("description") or "").strip()
        title_f = str(f.get("title") or f.get("clause") or "Clause").strip()
        if not issue:
            continue
        findings.append(ReviewFinding(
            title=title_f[:200], severity=sev,
            category=(str(f["category"]).lower()[:40] if f.get("category") else None),
            issue=issue,
            recommendation=(str(f["recommendation"]).strip() if f.get("recommendation") else None),
            clause_reference=(str(f["clause_reference"]).strip()[:80] if f.get("clause_reference") else None),
        ))

    # Highest finding severity should not undercut the overall risk.
    if any(f.severity == "high" for f in findings):
        risk = "high"

    return ContractReview(
        overall_risk=risk,
        summary=str(data.get("summary", "")).strip(),
        findings=findings,
        missing_clauses=_as_str_list(data.get("missing_clauses")),
        favorable_points=_as_str_list(data.get("favorable_points")),
        source=source,
        title=title,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
    )


def review_contract(
    user: User, *, text: str, source: str, contract_id: str | None = None, title: str | None = None,
) -> ContractReview:
    """Run the AI risk review over contract text (a Kora contract or one the user
    received) and log it. Returns a normalized ContractReview."""
    clean = (text or "").replace("\x00", "").strip()[:_MAX_REVIEW_CHARS]
    ai = get_ai()
    call = generate_with_retry(lambda: ai.review_contract({
        "text": clean,
        "business_name": user.business_name or user.full_name,
        "title": title,
    }))
    review = _normalize_review(call.data if isinstance(call.data, dict) else {}, source=source, title=title)

    agent_logger.log_action(
        user_id=user.id,
        # No 'contract_reviewer' value in the agent_logs CHECK constraint — log
        # under contract_generator; the action text marks it as a review.
        agent_type="contract_generator",
        action=f"Reviewed contract — {review.overall_risk} risk ({title or source})",
        input={"source": source, "chars": len(clean), "contractId": contract_id, "title": title},
        output={"overallRisk": review.overall_risk, "findings": len(review.findings),
                "missingClauses": len(review.missing_clauses), "summary": review.summary[:300]},
        model_used=call.model_used,
        tokens_used=call.tokens_used,
        latency_ms=call.latency_ms,
        cost_usd=call.cost_usd,
        triggered_by="user",
        source_record_type="contract",
        source_record_id=contract_id,
    )
    return review


# --- Persist a contract the user RECEIVED (so the Butler tracks it) ----------
_EXT_BY_CT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
}


def _ext_for(filename: str | None, content_type: str | None) -> str:
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext in ("pdf", "docx", "txt", "md"):
            return ext
    return _EXT_BY_CT.get(content_type or "", "pdf")


def save_received_contract(
    user: User,
    *,
    text: str,
    review: ContractReview,
    source: str,
    title: str | None = None,
    client_id: str | None = None,
    client_name: str | None = None,
    raw_bytes: bytes | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict:
    """Persist a contract the user received from a client: a Contract row (marked
    `_received`, linked to a client by name so the Butler surfaces it), the raw
    file in the bucket (best-effort), and — when a client is chosen — an
    Engagement so the Butler tracks the deliverable. Best-effort; never raises
    into the review flow. Returns {contractId, clientId, engagementId, savedFile}."""
    client = store.get_client(user.id, client_id) if client_id else None
    resolved_name = (client.name if client else (client_name or title or "Received contract")).strip()[:200]

    contract_id = store.uid("ctr")
    terms: dict = {
        "_received": True,
        "_source": source,
        "_review": review.model_dump(by_alias=True),
    }
    if client:
        terms["_client_id"] = client.id

    # Upload the original file (best-effort; only when storage is configured).
    saved_file = False
    if raw_bytes and storage.is_configured():
        try:
            ext = _ext_for(filename, content_type)
            path = storage.received_contract_path(user.id, contract_id, ext)
            storage.upload_bytes(user.id, path, raw_bytes, content_type or "application/octet-stream")
            terms["_gcs_path"] = path
            saved_file = True
        except Exception as exc:  # missing creds / bucket — keep the DB record
            print(f"[contract] received-file upload skipped: {exc}")

    contract = Contract(
        id=contract_id, user_id=user.id, type="service_contract",
        title=title or f"Received contract — {resolved_name}",
        client_name=resolved_name, provider_name=user.business_name or user.full_name,
        jurisdiction=user.country or "US", terms=terms, content_md=text,
        # 'sent' (allowed by the schema CHECK) = received from the client, not yet
        # signed by the owner; pairs with the supervisor's "awaiting signature" view.
        status="sent", created_at=_now_iso(),
    )
    try:
        store.insert_contract(contract)
    except Exception as exc:
        print(f"[contract] received-contract persist failed: {exc}")
        return {"contractId": None, "clientId": client.id if client else None,
                "engagementId": None, "savedFile": saved_file}

    # When linked to a client, create an engagement so the Butler tracks the work.
    engagement_id = None
    if client:
        try:
            eng = Engagement(
                id=store.uid("eng"), user_id=user.id, client_id=client.id,
                title=(title or f"{resolved_name} contract")[:200],
                description_md=(review.summary or "Work governed by a received contract.")[:2000],
                engagement_type="project", status="active",
                contract_id=contract_id, created_at=_now_iso(), updated_at=_now_iso(),
            )
            store.insert_engagement(eng)
            engagement_id = eng.id
            store.update_client(user.id, client.id, {"last_activity_at": _now_iso()})
        except Exception as exc:
            print(f"[contract] received-contract engagement skipped: {exc}")

    agent_logger.log_action(
        user_id=user.id, agent_type="butler",
        action=f"Saved received contract from {resolved_name} ({review.overall_risk} risk)",
        input={"source": source, "clientId": client.id if client else None, "savedFile": saved_file},
        output={"contractId": contract_id, "engagementId": engagement_id},
        triggered_by="user", source_record_type="contract", source_record_id=contract_id)

    return {"contractId": contract_id, "clientId": client.id if client else None,
            "engagementId": engagement_id, "savedFile": saved_file}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
