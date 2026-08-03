from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from .. import store
from ..dependencies import get_current_user
from ..models import ManagerTask, ProposalGenerateRequest, User
from ..services import proposal_agent
from ..utils.rate_limit import check_rate_limit

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
async def list_proposals(user: User = Depends(get_current_user)):
    return [p.model_dump(by_alias=True) for p in store.list_proposals(user.id)]


@router.get("/{proposal_id}")
async def get_proposal(proposal_id: str, user: User = Depends(get_current_user)):
    p = store.get_proposal(user.id, proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return p.model_dump(by_alias=True)


@router.post("/generate")
async def generate_proposal(body: ProposalGenerateRequest, user: User = Depends(get_current_user)):
    rl = check_rate_limit(f"ai:proposal:{user.id}", max_requests=10, window_seconds=3600)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Hourly proposal limit reached. Try again shortly.")
    proposal = proposal_agent.generate_proposal(user, body)
    return proposal.model_dump(by_alias=True)


@router.post("/{proposal_id}/accept")
async def accept_proposal(proposal_id: str, user: User = Depends(get_current_user)):
    """Accept → auto-generate a matching contract (cross-module)."""
    try:
        return proposal_agent.proposal_to_contract(user, proposal_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Proposal not found")


@router.post("/{proposal_id}/send")
async def send_proposal(proposal_id: str, user: User = Depends(get_current_user)):
    """Queue sending the proposal for the owner's approval (HITL — never auto-sends)."""
    p = store.get_proposal(user.id, proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    client_name = "the client"
    if p.client_id:
        c = store.get_client(user.id, p.client_id)
        if c:
            client_name = c.name
    if store.find_open_manager_task(user.id, "send_proposal", p.id):
        return {"queued": True, "new": False, "note": "Already awaiting your approval."}
    store.insert_manager_task(
        ManagerTask(
            id=store.uid("task"),
            user_id=user.id,
            kind="send_proposal",
            title=f"Send proposal {p.proposal_number or ''} to {client_name}".strip(),
            rationale=f"Proposal '{p.title}' for {p.currency} {p.total_amount:,.2f} is ready to send.",
            severity="info",
            status="proposed",
            payload={"proposalId": p.id, "title": p.title},
            source_record_type="proposal",
            source_record_id=p.id,
            created_at=_now(),
        )
    )
    return {"queued": True, "new": True}
