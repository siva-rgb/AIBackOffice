from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import store
from ..dependencies import get_current_user
from ..models import ObservationCreate, Story, StoryCreate, StoryUpdate, User
from ..services import story_ledger

router = APIRouter(prefix="/api/stories", tags=["stories"])


@router.get("", response_model=list[Story])
async def list_stories(
    task_id: str | None = None,
    client_id: str | None = None,
    open_only: bool = False,
    user: User = Depends(get_current_user),
):
    """Stories, optionally scoped to a task or a client."""
    return store.list_stories(
        user.id,
        task_id=task_id,
        client_id=client_id,
        statuses=story_ledger.OPEN_STATUSES if open_only else None,
    )


@router.get("/stats")
async def story_stats(
    task_id: str | None = None,
    client_id: str | None = None,
    user: User = Depends(get_current_user),
):
    """Progress + blocker counts — the headline numbers the M2 roll-up builds on."""
    return story_ledger.stats(user.id, task_id=task_id, client_id=client_id)


@router.post("", response_model=Story, status_code=201)
async def create_story(payload: StoryCreate, user: User = Depends(get_current_user)):
    try:
        return story_ledger.create_story(user.id, payload.model_dump(by_alias=False))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not create the story. Ensure the 'stories' table exists " "(run migrations/2026-07-23_add_stories.sql). " + str(exc)[:160],
        )


@router.patch("/{story_id}", response_model=Story)
async def update_story(story_id: str, payload: StoryUpdate, user: User = Depends(get_current_user)):
    updated = story_ledger.update_story(user.id, story_id, payload.model_dump(by_alias=False, exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Story not found")
    return updated


@router.delete("/{story_id}", status_code=204)
async def delete_story(story_id: str, user: User = Depends(get_current_user)):
    if not story_ledger.delete_story(user.id, story_id):
        raise HTTPException(status_code=404, detail="Story not found")
    return None


# ── Observations ────────────────────────────────────────────────────────────


@router.post("/{story_id}/observations", response_model=Story, status_code=201)
async def add_observation(story_id: str, payload: ObservationCreate, user: User = Depends(get_current_user)):
    """Attach an evidence-backed observation.

    `source_ref` is required by the schema — an observation that cannot be traced
    to an email, meeting or document is rejected with 422 before reaching here.
    """
    try:
        updated = story_ledger.add_observation(
            user.id,
            story_id,
            kind=payload.kind,
            text=payload.text,
            source=payload.source,
            source_ref=payload.source_ref,
            # Anything arriving through the API is a human acting, so it is
            # protected from being overwritten by the nightly agent refresh.
            user_edited=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="Story not found")
    return updated


@router.patch("/{story_id}/observations/{observation_id}", response_model=Story)
async def edit_observation(
    story_id: str,
    observation_id: str,
    payload: ObservationCreate,
    user: User = Depends(get_current_user),
):
    """Correct an observation — flags it so agent refreshes leave it alone."""
    updated = story_ledger.edit_observation(user.id, story_id, observation_id, payload.text)
    if not updated:
        raise HTTPException(status_code=404, detail="Story not found")
    return updated


@router.delete("/{story_id}/observations/{observation_id}", response_model=Story)
async def remove_observation(story_id: str, observation_id: str, user: User = Depends(get_current_user)):
    updated = story_ledger.remove_observation(user.id, story_id, observation_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Story not found")
    return updated
