from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header

from .. import store
from ..config import settings
from ..dependencies import get_current_user, verify_cron_secret
from ..models import CamelModel, User
from ..seed import DEMO_USER_ID
from ..services import memory_recall

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _scheduler_user_id() -> str:
    if settings.KORA_DATA_BACKEND == "supabase":
        u = store.get_user_by_email(settings.DEMO_EMAIL)
        if u:
            return u.id
    return DEMO_USER_ID


class RecallRequest(CamelModel):
    query: str
    client_id: str | None = None
    k: int = 6


@router.post("/recall")
async def recall_memory(req: RecallRequest, user: User = Depends(get_current_user)):
    """Hybrid semantic recall over the user's durable agent memory. Debug/UI entry
    point; agents use the `recall_memory` tool + the assemble_context tier."""
    hits = memory_recall.recall(user.id, req.query, k=req.k, client_id=req.client_id)
    return {
        "query": req.query,
        "results": [
            {"content": h["content"], "kind": h.get("kind"), "clientId": h.get("client_id"),
             "source": h.get("source"), "score": h.get("_score"),
             "similarity": h.get("_sim"), "lexical": h.get("_lex")}
            for h in hits
        ],
    }


@router.get("/stats")
async def memory_stats(user: User = Depends(get_current_user)):
    """Row/embedding counts + whether semantic ranking is active."""
    return memory_recall.stats(user.id)


@router.post("/reindex")
async def reindex_memory(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    """Backfill agent_memory from the structured stores + embed missing rows.
    Scheduler path uses x-cron-secret (async); a user path runs inline so the
    response carries the counts."""
    if is_cron:
        background_tasks.add_task(memory_recall.reindex, _scheduler_user_id())
        return {"status": "reindexing", "trigger": "scheduler"}
    user = await get_current_user(authorization)
    return memory_recall.reindex(user.id)
