from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from .. import store
from ..config import settings
from ..dependencies import get_current_user, verify_cron_secret
from ..models import User
from ..seed import DEMO_USER_ID
from ..entitlements import enforce_plan
from ..services.graph_memory import sync_graph, query_subgraph
from ..utils.casing import camelize

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _scheduler_user_id() -> str:
    if settings.KORA_DATA_BACKEND == "supabase":
        u = store.get_user_by_email(settings.DEMO_EMAIL)
        if u:
            return u.id
    return DEMO_USER_ID


@router.get("")
async def get_graph(user: User = Depends(get_current_user)):
    """The user's full relationship graph (nodes + edges) for visualization."""
    return {
        "nodes": camelize(store.get_kg_nodes(user.id)),
        "edges": camelize(store.get_kg_edges(user.id)),
    }


@router.post("/sync", dependencies=[Depends(enforce_plan)])
async def sync(user: User = Depends(get_current_user)):
    """Rebuild the user's graph from current data (manual 'Rebuild memory')."""
    return sync_graph(user.id, rebuild=True)


@router.post("/run")
async def run_graph(
    request: Request,
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    """Scheduled graph sync. Scheduler path uses x-cron-secret; a user path (auth)
    also works for a manual run."""
    if is_cron:
        return {"trigger": "scheduler", **sync_graph(_scheduler_user_id())}
    user = await get_current_user(request, authorization)
    return {"trigger": "user", **sync_graph(user.id)}


@router.get("/client/{client_id}")
async def client_subgraph(client_id: str, user: User = Depends(get_current_user)):
    """Everything linked to one client (records + learned facts)."""
    return query_subgraph(user.id, client_id)
