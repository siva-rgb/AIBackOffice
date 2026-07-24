from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from .. import store
from ..dependencies import get_current_user
from ..entitlements import enforce_plan
from ..models import (
    Contract,
    ContractReview,
    GenerateContractRequest,
    ReviewTextRequest,
    UpdateContractStatusRequest,
    User,
)
from ..services.contract_agent import generate_contract, review_contract, save_received_contract
from ..services.cross_module import on_contract_signed
from ..services.pdf_generator import generate_contract_pdf
from ..utils.document_text import UnsupportedDocument, extract_text
from ..utils.rate_limit import check_rate_limit

_MAX_UPLOAD = 5 * 1024 * 1024  # 5 MB

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.get("", response_model=list[Contract])
async def list_contracts(user: User = Depends(get_current_user)):
    return store.list_contracts(user.id)


@router.post("/generate", response_model=Contract, status_code=201,
             dependencies=[Depends(enforce_plan)])
async def generate(body: GenerateContractRequest, user: User = Depends(get_current_user)):
    # Rate limit the AI endpoint (SKILL.md §16 Rule 5: contracts 10/hour/user).
    rl = check_rate_limit(f"ai:contract:{user.id}", max_requests=10, window_seconds=3600)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Rate limit reached. Try again shortly.")
    return generate_contract(user, body)


def _check_review_limit(user_id: str) -> None:
    rl = check_rate_limit(f"ai:review:{user_id}", max_requests=15, window_seconds=3600)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Rate limit reached. Try again shortly.")


def _review_response(review: ContractReview, saved: dict | None) -> dict:
    """The review payload plus, when persisted, the saved record's IDs. Extra
    keys are ignored by the existing reviewer UI (backward compatible)."""
    out = review.model_dump(by_alias=True)
    if saved:
        out["saved"] = saved
    return out


@router.post("/review", dependencies=[Depends(enforce_plan)])
async def review_pasted(body: ReviewTextRequest, user: User = Depends(get_current_user)):
    """Review a contract the user received, pasted as text. Optionally save it so
    the Butler tracks it against a client (pass clientId, or save=true)."""
    _check_review_limit(user.id)
    review = review_contract(user, text=body.text, source="paste", title=body.title)
    saved = None
    if body.save or body.client_id:
        saved = save_received_contract(
            user, text=body.text, review=review, source="paste", title=body.title,
            client_id=body.client_id, client_name=body.client_name)
    return _review_response(review, saved)


@router.post("/review/upload", dependencies=[Depends(enforce_plan)])
async def review_upload(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    client_id: str | None = Form(default=None, alias="clientId"),
    save: bool = Form(default=True),
    user: User = Depends(get_current_user),
):
    """Review a contract the user received (PDF / DOCX / text). Saved by default so
    the Butler tracks it — pass clientId to link it to a client (creates an
    engagement), or save=false to review without storing."""
    _check_review_limit(user.id)
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="File too large (max 5MB)")
    try:
        text = extract_text(file.filename or "", file.content_type, raw)
    except UnsupportedDocument as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    review = review_contract(user, text=text, source="upload", title=title or file.filename)
    saved = None
    if save or client_id:
        saved = save_received_contract(
            user, text=text, review=review, source="upload", title=title or file.filename,
            client_id=client_id, raw_bytes=raw, filename=file.filename, content_type=file.content_type)
    return _review_response(review, saved)


@router.post("/{contract_id}/review", response_model=ContractReview,
             dependencies=[Depends(enforce_plan)])
async def review_existing(contract_id: str, user: User = Depends(get_current_user)):
    """Review a contract Kora generated."""
    _check_review_limit(user.id)
    c = store.get_contract(user.id, contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    if not c.content_md:
        raise HTTPException(status_code=409, detail="Contract has no content to review")
    return review_contract(user, text=c.content_md, source="kora",
                           contract_id=contract_id, title=c.title)


@router.get("/{contract_id}", response_model=Contract)
async def get_contract(contract_id: str, user: User = Depends(get_current_user)):
    c = store.get_contract(user.id, contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    return c


@router.get("/{contract_id}/pdf")
async def contract_pdf(contract_id: str, user: User = Depends(get_current_user)):
    c = store.get_contract(user.id, contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    if not c.content_md:
        raise HTTPException(status_code=409, detail="Contract has no content yet")
    pdf = generate_contract_pdf(c.title or "Contract", c.content_md)
    safe = (c.title or "contract").lower().replace(" ", "-").replace("—", "-")
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="kora-{safe}.pdf"'},
    )


@router.patch("/{contract_id}/status", response_model=Contract)
async def update_status(
    contract_id: str, body: UpdateContractStatusRequest, user: User = Depends(get_current_user)
):
    c = store.get_contract(user.id, contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    was_signed = c.status == "signed"
    patch = {"status": body.status}
    if body.status == "signed":
        patch["signed_at"] = datetime.now(timezone.utc).isoformat()
    updated = store.update_contract(user.id, contract_id, patch)

    # Cross-module trigger: contract signed → auto-create invoices (once).
    created = []
    if body.status == "signed" and not was_signed and updated:
        created = on_contract_signed(user.id, updated)

    return updated
