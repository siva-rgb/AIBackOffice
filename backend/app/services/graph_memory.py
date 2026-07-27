"""Agent graph memory.

A per-user knowledge graph (kg_nodes + kg_edges) the agents traverse for entities
and their relationships. Postgres/​memory is the source of truth; this module

  1. materializes the graph from existing rows — `sync_graph` (idempotent),
  2. lets learned intelligence flow in — `ingest_fact` (bridged from the Playbook
     observers), and
  3. serves focused context back to the LLMs — `build_graph_brief` (prompt text)
     and `query_subgraph` (structured, for the Manager tool + API/UI).

Design: small per-user graphs (100s–1000s of nodes), so we load the whole user
graph and traverse in Python — no graph DB, no recursive CTEs. Everything is
user-scoped (RLS in Supabase). Clients are the hubs: each client's invoices,
contracts, engagements, proposals, retainers and facts hang off its node, so
"everything about client X" is a 1-hop neighborhood — the same node-identity that
finally unifies name-matched invoices/contracts with id-linked records.
"""

from __future__ import annotations

from typing import Any

from .. import store
from .butler import _norm  # case-insensitive client-name match (single source)

# Node / edge vocabularies (kept small & readable; serialized into prompts).
N_BUSINESS, N_OWNER, N_CLIENT = "business", "owner", "client"
N_INVOICE, N_CONTRACT, N_ENGAGEMENT = "invoice", "contract", "engagement"
N_PROPOSAL, N_RETAINER = "proposal", "retainer"
N_OFFERING, N_PERSONA, N_GOAL, N_FACT = "offering", "persona", "goal", "fact"
N_TASK = "task"


def _money(cur: str, amt: Any) -> str:
    try:
        return f"{cur} {float(amt):,.0f}"
    except (TypeError, ValueError):
        return f"{cur} {amt}"


# ── Upsert helpers ──────────────────────────────────────────────────────────
def _node(user_id: str, node_type: str, entity_id: str | None, label: str, props: dict | None = None, salience: float = 0.5) -> str:
    row = store.upsert_kg_node(
        user_id,
        {
            "node_type": node_type,
            "entity_id": entity_id,
            "label": label or node_type,
            "props": props or {},
            "salience": salience,
        },
    )
    return row["id"]


def _edge(user_id: str, src_id: str, dst_id: str, rel: str, weight: float = 1, props: dict | None = None) -> None:
    if not src_id or not dst_id:
        return
    store.upsert_kg_edge(
        user_id,
        {
            "src_id": src_id,
            "dst_id": dst_id,
            "rel": rel,
            "weight": weight,
            "props": props or {},
        },
    )


# ── Materialization ─────────────────────────────────────────────────────────
def sync_graph(user_id: str, *, rebuild: bool = False) -> dict:
    """Rebuild the user's graph from current data. Idempotent (upsert + max-weight),
    so it is safe to run on a schedule. `rebuild=True` wipes first (clears removed
    entities). Returns simple counts."""
    if rebuild:
        store.delete_kg_for_user(user_id)

    user = store.get_user(user_id)
    profile = (user.profile.model_dump(by_alias=False) if user and hasattr(user.profile, "model_dump") else {}) or {}
    biz_label = getattr(user, "business_name", None) or profile.get("business_name") or "My business"
    biz = _node(user_id, N_BUSINESS, user_id, biz_label, {"businessType": profile.get("business_type")}, 1.0)

    owner_label = profile.get("display_name") or getattr(user, "full_name", None) or "Owner"
    owner = _node(user_id, N_OWNER, user_id, owner_label, {}, 0.9)
    _edge(user_id, owner, biz, "OWNS")

    # Profile-derived concept nodes
    for off in profile.get("offerings") or []:
        if isinstance(off, dict) and (off.get("name") or "").strip():
            oid = _node(user_id, N_OFFERING, None, off["name"], {"pricing": off.get("pricing")}, 0.55)
            _edge(user_id, biz, oid, "OFFERS")
    cust = profile.get("customers") or {}
    for persona in (cust.get("buyer_personas") or []) if isinstance(cust, dict) else []:
        if isinstance(persona, dict) and (persona.get("name") or "").strip():
            pid = _node(user_id, N_PERSONA, None, persona["name"], {"description": persona.get("description")}, 0.55)
            _edge(user_id, biz, pid, "HAS_PERSONA")
    if profile.get("financial_goals"):
        gid = _node(user_id, N_GOAL, None, str(profile["financial_goals"])[:120], {}, 0.6)
        _edge(user_id, biz, gid, "PURSUES_GOAL")

    # Clients (hubs)
    clients = store.list_clients(user_id)
    client_node: dict[str, str] = {}  # client.id -> node id
    client_by_name: dict[str, Any] = {}  # normalized name -> client
    for c in clients:
        risky = c.health_label in ("at_risk", "critical", "needs_attention")
        sal = 0.85 if c.health_label in ("at_risk", "critical") else (0.7 if risky else 0.55)
        nid = _node(
            user_id,
            N_CLIENT,
            c.id,
            c.name,
            {
                "status": c.status,
                "healthLabel": c.health_label,
                "industry": c.industry,
                "company": c.company,
            },
            sal,
        )
        client_node[c.id] = nid
        client_by_name[_norm(c.name)] = c
        _edge(user_id, biz, nid, "WORKS_ON")

    def _hub_for_name(name: str | None) -> str:
        """Resolve an invoice/contract's client hub by name-match, else the business."""
        c = client_by_name.get(_norm(name)) if name else None
        return client_node.get(c.id) if c else biz

    # Invoices (ISSUED / PAID)
    for inv in store.list_invoices(user_id):
        paid = inv.status == "paid"
        rel = "PAID" if paid else "ISSUED"
        overdue = inv.status == "overdue"
        sal = 0.75 if overdue else (0.5 if paid else 0.65)
        nid = _node(
            user_id,
            N_INVOICE,
            inv.id,
            inv.invoice_number,
            {
                "status": inv.status,
                "amount": inv.total,
                "currency": inv.currency,
                "dueDate": inv.due_date,
            },
            sal,
        )
        _edge(user_id, _hub_for_name(inv.client_name), nid, rel, weight=2 if overdue else 1, props={"status": inv.status})

    # Contracts (SIGNED / RELATED_TO)
    for ct in store.list_contracts(user_id):
        signed = ct.status == "signed"
        nid = _node(
            user_id,
            N_CONTRACT,
            ct.id,
            ct.title or ct.type,
            {
                "type": ct.type,
                "status": ct.status,
            },
            0.6 if signed else 0.5,
        )
        _edge(user_id, _hub_for_name(ct.client_name), nid, "SIGNED" if signed else "RELATED_TO", props={"status": ct.status})

    # Engagements / proposals / retainers (real client_id links)
    for eng in store.list_engagements(user_id):
        hub = client_node.get(eng.client_id)
        if not hub:
            continue
        nid = _node(
            user_id,
            N_ENGAGEMENT,
            eng.id,
            eng.title,
            {
                "status": eng.status,
                "type": eng.engagement_type,
                "budget": eng.budget,
            },
            0.6,
        )
        _edge(user_id, hub, nid, "HAS_ENGAGEMENT", props={"status": eng.status})

    for pr in store.list_proposals(user_id):
        hub = client_node.get(pr.client_id) if pr.client_id else None
        nid = _node(user_id, N_PROPOSAL, pr.id, pr.title, {"status": pr.status, "amount": pr.total_amount}, 0.55)
        _edge(user_id, hub or biz, nid, "PROPOSED", props={"status": pr.status})

    for rt in store.list_retainers(user_id):
        hub = client_node.get(rt.client_id) if rt.client_id else None
        nid = _node(user_id, N_RETAINER, rt.id, rt.title, {"amount": rt.amount, "cycle": rt.billing_cycle}, 0.6)
        _edge(user_id, hub or biz, nid, "RETAINS", props={"status": rt.status})

    # Open tasks (the work owed) — overdue/blocked ones carry higher salience so
    # they surface first in a client's neighbourhood.
    try:
        from .task_ledger import OPEN_STATUSES, is_overdue

        for t in store.list_tasks(user_id, statuses=OPEN_STATUSES):
            hub = client_node.get(t.client_id) if t.client_id else None
            overdue = is_overdue(t)
            sal = 0.85 if overdue else (0.7 if t.status == "blocked" else 0.55)
            nid = _node(
                user_id,
                N_TASK,
                t.id,
                t.title,
                {
                    "status": t.status,
                    "priority": t.priority,
                    "dueDate": t.due_date,
                    "overdue": overdue,
                },
                sal,
            )
            _edge(user_id, hub or biz, nid, "HAS_TASK", weight=2 if overdue else 1, props={"status": t.status})
    except Exception as exc:
        print(f"[graph] task nodes skipped: {exc}")

    nodes = store.get_kg_nodes(user_id)
    edges = store.get_kg_edges(user_id)
    return {"nodes": len(nodes), "edges": len(edges), "clients": len(clients)}


# ── Learned facts (bridged from Playbook observers) ─────────────────────────
def ingest_fact(
    user_id: str,
    *,
    subject_type: str,
    subject_label: str,
    rel: str,
    object_label: str,
    subject_entity_id: str | None = None,
    object_type: str = N_FACT,
    object_entity_id: str | None = None,
    props: dict | None = None,
    salience: float = 0.6,
) -> None:
    """Add a learned fact/relationship. Safe to call from observers (best-effort)."""
    try:
        sid = _node(user_id, subject_type, subject_entity_id, subject_label, {}, salience)
        oid = _node(user_id, object_type, object_entity_id, object_label[:160], props or {}, salience)
        _edge(user_id, sid, oid, rel, props=props or {})
        # Semantic memory bridge — make the fact recallable by meaning. ref_id is
        # the fact node id, so reindex() (which scans fact nodes) upserts the same
        # row rather than duplicating. Best-effort; never blocks graph ingest.
        if object_type == N_FACT:
            try:
                from .memory_recall import remember

                remember(
                    user_id,
                    "graph_fact",
                    object_label,
                    client_id=(subject_entity_id if subject_type == N_CLIENT else None),
                    ref_type="kg_node",
                    ref_id=oid,
                    salience=salience,
                    source=(props or {}).get("source"),
                )
            except Exception:
                pass
    except Exception:
        pass


def ingest_client_fact(
    user_id: str, client_id: str | None, client_name: str | None, summary: str, *, rel: str = "MENTIONS", source: str | None = None
) -> None:
    """Convenience for the client-intelligence observers (email intel, meetings)."""
    if not (client_name or client_id) or not summary:
        return
    # Resolve the real client name so we don't overwrite the client node's label
    # with a generic placeholder (node identity is by entity_id).
    if not client_name and client_id:
        try:
            c = store.get_client(user_id, client_id)
            client_name = c.name if c else None
        except Exception:
            client_name = None
    ingest_fact(
        user_id,
        subject_type=N_CLIENT,
        subject_label=client_name or "Client",
        subject_entity_id=client_id,
        rel=rel,
        object_label=summary,
        props={"source": source} if source else {},
    )


# ── Traversal + retrieval ───────────────────────────────────────────────────
def _load(user_id: str) -> tuple[dict[str, dict], list[dict]]:
    nodes = {n["id"]: n for n in store.get_kg_nodes(user_id)}
    edges = store.get_kg_edges(user_id)
    return nodes, edges


def _neighbors(node_id: str, nodes: dict[str, dict], edges: list[dict]) -> list[tuple[str, dict, str]]:
    """Return [(rel, other_node, direction)] for a node (1 hop). direction is
    'out' when node is the edge source, 'in' otherwise."""
    out: list[tuple[str, dict, str]] = []
    for e in edges:
        if e["src_id"] == node_id and e["dst_id"] in nodes:
            out.append((e["rel"], nodes[e["dst_id"]], "out"))
        elif e["dst_id"] == node_id and e["src_id"] in nodes:
            out.append((e["rel"], nodes[e["src_id"]], "in"))
    return out


def _resolve_client_node(nodes: dict[str, dict], *, client_id: str | None = None, name: str | None = None) -> dict | None:
    for n in nodes.values():
        if n["node_type"] != N_CLIENT:
            continue
        if client_id and n.get("entity_id") == client_id:
            return n
        if name and _norm(n.get("label")) == _norm(name):
            return n
    return None


def _describe_neighbor(rel: str, node: dict) -> str:
    label = node.get("label", "?")
    props = node.get("props") or {}
    if node["node_type"] == N_INVOICE and props.get("amount") is not None:
        return f"{rel} invoice {label} ({_money(props.get('currency', ''), props.get('amount'))}, {props.get('status', '')})"
    if node["node_type"] == N_CONTRACT:
        return f"{rel} contract '{label}' ({props.get('status', '')})"
    if node["node_type"] == N_ENGAGEMENT:
        return f"{rel} engagement '{label}' ({props.get('status', '')})"
    if node["node_type"] in (N_PROPOSAL, N_RETAINER):
        return f"{rel} {node['node_type']} '{label}'"
    if node["node_type"] == N_TASK:
        flag = " OVERDUE" if props.get("overdue") else ""
        due = f", due {str(props.get('dueDate'))[:10]}" if props.get("dueDate") else ""
        return f"task '{label}' ({props.get('status', '')}{due}){flag}"
    if node["node_type"] == N_FACT:
        return f"note: {label}"
    return f"{rel} {node['node_type']} '{label}'"


def _client_line(cnode: dict, nodes: dict[str, dict], edges: list[dict], max_items: int = 8) -> str:
    nb = _neighbors(cnode["id"], nodes, edges)
    # Drop the business hub back-link; keep record/fact edges.
    items = [(rel, n) for (rel, n, _d) in nb if n["node_type"] != N_BUSINESS]
    parts = [_describe_neighbor(rel, n) for rel, n in items[:max_items]]
    health = (cnode.get("props") or {}).get("healthLabel")
    head = cnode.get("label", "Client") + (f" [{health}]" if health and health != "on_track" else "")
    return f"{head}: " + ("; ".join(parts) if parts else "no linked records") + "."


def build_graph_brief(
    user_id: str, task_type: str = "briefing", client_id: str | None = None, client_name: str | None = None, max_chars: int = 700
) -> str:
    """Serialize a focused subgraph for prompt injection, or "" when empty.

    Client in focus → that client's neighborhood. Otherwise → the top-salience
    clients (so a user with many clients doesn't flood the context)."""
    nodes, edges = _load(user_id)
    if not nodes:
        return ""

    lines: list[str] = []
    focus = _resolve_client_node(nodes, client_id=client_id, name=client_name) if (client_id or client_name) else None
    if focus:
        lines.append(_client_line(focus, nodes, edges, max_items=12))
    else:
        clients = [n for n in nodes.values() if n["node_type"] == N_CLIENT]
        clients.sort(key=lambda n: float(n.get("salience", 0)), reverse=True)
        for c in clients[:6]:
            lines.append(_client_line(c, nodes, edges, max_items=6))

    if not lines:
        return ""
    combined = "Relationship memory:\n" + "\n".join(lines)
    if len(combined) > max_chars:
        combined = combined[:max_chars].rsplit("\n", 1)[0]
    return combined


def query_subgraph(user_id: str, focus: str) -> dict:
    """Structured neighborhood for the Manager's tool + the API/UI. `focus` is a
    client name (or id). Returns the focus label and its relations."""
    nodes, edges = _load(user_id)
    cnode = _resolve_client_node(nodes, client_id=focus, name=focus)
    if not cnode:
        return {"found": False, "focus": focus, "relations": []}
    relations = [
        {"rel": rel, "type": n["node_type"], "label": n.get("label"), "props": n.get("props") or {}}
        for (rel, n, _d) in _neighbors(cnode["id"], nodes, edges)
        if n["node_type"] != N_BUSINESS
    ]
    return {
        "found": True,
        "focus": cnode.get("label"),
        "health": (cnode.get("props") or {}).get("healthLabel"),
        "relations": relations,
    }
