from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .. import store
from ..models import Contract, GenerateContractRequest, Proposal, ProposalGenerateRequest, User
from ..utils.security import safe_sanitize
from . import agent_logger
from .contract_agent import generate_contract
from .vertex_ai import generate_with_retry, get_ai

# Proposal generator (manager_skill Phase 4). Closes the top of the deal funnel:
# proposal → (accept) → contract → invoice. Reuses the contract_generator infra
# for the accept path. One LLM call per generation.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_client(user: User, req: ProposalGenerateRequest) -> tuple[str | None, str, str | None]:
    """Return (client_id, client_name, client_email) from either a linked client or raw input."""
    if req.client_id:
        c = store.get_client(user.id, req.client_id)
        if c:
            return c.id, c.name, c.email
    return None, (req.client_name or "Client"), req.client_email


def _proposal_number(user_id: str) -> str:
    year = datetime.now(timezone.utc).year
    n = sum(1 for p in store.list_proposals(user_id) if (p.proposal_number or "").startswith(f"PROP-{year}"))
    return f"PROP-{year}-{n + 1:03d}"


def generate_proposal(user: User, req: ProposalGenerateRequest) -> Proposal:
    client_id, client_name, client_email = _resolve_client(user, req)
    valid_until = (date.today() + timedelta(days=req.valid_days)).isoformat()

    payload = {
        "business_name": user.business_name or user.full_name or "Service Provider",
        "client_name": safe_sanitize(client_name),
        "title": safe_sanitize(req.title),
        "scope_description": safe_sanitize(req.scope_description),
        "deliverables_raw": safe_sanitize(req.deliverables_raw),
        "timeline_description": safe_sanitize(req.timeline_description),
        "total_amount": req.total_amount,
        "currency": req.currency,
        "pricing_type": req.pricing_type,
        "payment_terms": req.payment_terms,
        "valid_until": valid_until,
    }
    try:
        from .playbook import assemble_context
        business_context = assemble_context(user.id, "proposal")
        if business_context:
            payload["business_context"] = business_context
    except Exception:
        pass
    call = generate_with_retry(lambda: get_ai().generate_proposal(payload))
    content_md = call.data.get("content_md")

    proposal = Proposal(
        id=store.uid("prop"), user_id=user.id, client_id=client_id,
        title=req.title, proposal_number=_proposal_number(user.id),
        scope_md=req.scope_description, deliverables_md=req.deliverables_raw,
        timeline_md=req.timeline_description, content_md=content_md,
        section_explanations=call.data.get("section_explanations", {}),
        total_amount=req.total_amount, currency=req.currency, pricing_type=req.pricing_type,
        payment_terms=req.payment_terms, status="draft", valid_until=valid_until,
        created_at=_now(),
    )
    store.insert_proposal(proposal)

    agent_logger.log_action(
        user_id=user.id, agent_type="butler",
        action=f"Generated proposal '{req.title}' for {client_name}",
        input={"title": req.title, "total": req.total_amount, "clientId": client_id},
        output={"proposalId": proposal.id, "number": proposal.proposal_number},
        model_used=call.model_used, tokens_used=call.tokens_used, latency_ms=call.latency_ms,
        cost_usd=call.cost_usd, triggered_by="user", source_record_type="proposal",
        source_record_id=proposal.id)
    return proposal


# --- Proposal type → contract type mapping ----------------------------------
_PRICING_TO_CONTRACT = {
    "fixed": "freelance_agreement", "hourly": "service_contract",
    "retainer": "service_contract", "milestone": "freelance_agreement",
}


def proposal_to_contract(user: User, proposal_id: str) -> dict:
    """Accept a proposal → auto-generate a matching contract (cross-module)."""
    proposal = store.get_proposal(user.id, proposal_id)
    if not proposal:
        raise LookupError("Proposal not found")
    if proposal.contract_id:
        return {"proposalId": proposal.id, "contractId": proposal.contract_id, "note": "Already converted."}

    client_name = "Client"
    client_email = None
    jurisdiction = "US"
    if proposal.client_id:
        c = store.get_client(user.id, proposal.client_id)
        if c:
            client_name, client_email = c.name, c.email
    user_obj = store.get_user(user.id)
    if user_obj and user_obj.profile and getattr(user_obj.profile, "address", None):
        jurisdiction = user_obj.country or "US"

    ctype = _PRICING_TO_CONTRACT.get(proposal.pricing_type, "freelance_agreement")
    req = GenerateContractRequest(
        type=ctype, client_name=client_name, client_email=client_email,
        provider_name=user.business_name or user.full_name, jurisdiction=jurisdiction,
        terms={
            "project_description": proposal.scope_md or proposal.title,
            "deliverables": proposal.deliverables_md or "",
            "total_fee": proposal.total_amount,
            "payment_schedule": proposal.payment_terms or "",
            "timeline": proposal.timeline_md or "",
            "from_proposal": proposal.proposal_number,
        },
    )
    contract: Contract = generate_contract(user_obj or user, req)

    store.update_proposal(user.id, proposal.id, {
        "status": "accepted", "accepted_at": _now(), "contract_id": contract.id})

    agent_logger.log_action(
        user_id=user.id, agent_type="butler",
        action=f"Accepted proposal {proposal.proposal_number} → generated contract",
        input={"proposalId": proposal.id},
        output={"contractId": contract.id, "contractType": ctype},
        model_used="cross_module", triggered_by="cross_module",
        source_record_type="proposal", source_record_id=proposal.id)

    return {"proposalId": proposal.id, "contractId": contract.id, "contractType": ctype}
