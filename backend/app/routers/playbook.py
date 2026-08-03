from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import store
from ..dependencies import get_current_user
from ..models import PlaybookCreate, PlaybookUpdate, User

router = APIRouter(prefix="/api/playbook", tags=["playbook"])


def _entry_to_dict(e) -> dict:
    return e if isinstance(e, dict) else e.model_dump(by_alias=True)


@router.get("")
async def list_entries(
    category: str | None = None,
    client_id: str | None = None,
    min_confidence: float = 0.0,
    user: User = Depends(get_current_user),
):
    entries = store.get_playbook_entries(user.id, category=category, client_id=client_id, min_confidence=min_confidence)
    return [_entry_to_dict(e) for e in entries]


@router.post("", status_code=201)
async def create_entry(body: PlaybookCreate, user: User = Depends(get_current_user)):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    entry_dict = {
        "id": store.uid("pb"),
        "user_id": user.id,
        "category": body.category,
        "client_id": body.client_id,
        "key": body.key,
        "value": body.value,
        "summary": body.summary,
        "confidence": body.confidence,
        "source": body.source,
        "observation_count": 1,
        "first_observed_at": now,
        "last_observed_at": now,
        "expires_at": None,
        "created_at": now,
    }
    result = store.upsert_playbook_entry(user.id, entry_dict)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create entry")
    return _entry_to_dict(result)


@router.patch("/{entry_id}")
async def update_entry(entry_id: str, body: PlaybookUpdate, user: User = Depends(get_current_user)):
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = store.update_playbook_entry(user.id, entry_id, patch)
    if not result:
        raise HTTPException(status_code=404, detail="Entry not found")
    return _entry_to_dict(result)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(entry_id: str, user: User = Depends(get_current_user)):
    deleted = store.delete_playbook_entry(user.id, entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")


@router.post("/detect")
async def detect_patterns(user: User = Depends(get_current_user)):
    from ..services.playbook import detect_patterns

    patterns = detect_patterns(user.id)
    return {"detected": len(patterns), "patterns": patterns}


@router.post("/compress")
async def compress_memory(user: User = Depends(get_current_user)):
    from ..services.playbook import compress_playbook_to_memory

    result = compress_playbook_to_memory(user.id)
    return {"ok": True, "summary": result}


@router.get("/stats")
async def get_stats(user: User = Depends(get_current_user)):
    entries = store.get_playbook_entries(user.id)

    def _get(e, field, default=None):
        return e.get(field, default) if isinstance(e, dict) else getattr(e, field, default)

    corrections = [e for e in entries if _get(e, "confidence", 0) == 1.0 or _get(e, "category", "") == "correction"]
    high_confidence = [e for e in entries if _get(e, "confidence", 0) >= 0.7]
    patterns = [e for e in entries if _get(e, "category", "") in ("business_pattern", "business_rule")]
    by_category: dict[str, int] = {}
    for e in entries:
        cat = _get(e, "category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1
    return {
        "total": len(entries),
        "corrections": len(corrections),
        "highConfidence": len(high_confidence),
        "patterns": len(patterns),
        "byCategory": by_category,
    }
