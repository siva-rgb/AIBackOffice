from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import store
from ..dependencies import get_current_user
from ..models import Task, TaskCreate, TaskUpdate, User
from ..services import task_ledger

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
async def list_tasks(
    client_id: str | None = None,
    engagement_id: str | None = None,
    status: str | None = None,
    open_only: bool = False,
    user: User = Depends(get_current_user),
):
    """The task ledger. `open_only=true` returns todo/in_progress/blocked."""
    return store.list_tasks(
        user.id,
        client_id=client_id,
        engagement_id=engagement_id,
        status=status,
        statuses=task_ledger.OPEN_STATUSES if (open_only and not status) else None,
    )


@router.get("/stats")
async def task_stats(user: User = Depends(get_current_user)):
    """Counts the dashboard/briefing use: open, overdue, blocked, due today."""
    return task_ledger.stats(user.id)


@router.post("", response_model=Task, status_code=201)
async def create_task(payload: TaskCreate, user: User = Depends(get_current_user)):
    try:
        return task_ledger.create_task(user.id, payload.model_dump(by_alias=False))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not create the task. Ensure the 'tasks' table exists " "(run migrations/2026-07-17_add_tasks.sql). " + str(exc)[:160],
        )


@router.patch("/{task_id}", response_model=Task)
async def update_task(task_id: str, payload: TaskUpdate, user: User = Depends(get_current_user)):
    updated = task_ledger.update_task(user.id, task_id, payload.model_dump(by_alias=False, exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    return updated


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str, user: User = Depends(get_current_user)):
    if not store.delete_task(user.id, task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return None
