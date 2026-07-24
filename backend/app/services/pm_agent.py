"""PM agent fan-out — a team of narrow analysts that keep each client's view current.

The shape mirrors how a human delivery team actually divides the work: four
specialists each look at one facet of a client relationship, and a project
manager stitches their notes together. Here the specialists are LLM calls and
the project manager is **code**.

Three properties are load-bearing, and each is enforced by a test:

**1. The merge is deterministic — never an LLM.** `compose_client_view` runs the
four analysts, then assembles the view in plain Python. No model decides the
final shape, the ordering, or — critically — any number. This is what makes a
client's headline health reproducible and free to serve.

**2. No figure originates from a model.** Analysts write *prose*; every
authoritative number (money owed, % complete, blocker counts) comes from the
ledger via `_gather`. `_strip_unverified_figures` then redacts any currency or
percentage an analyst emitted that is not in the ground-truth set — so a
hallucinated "$99,999" can never reach the user as if it were real.

**3. One analyst failing degrades only its section.** Each analyst runs inside
its own guard; an exception (or an unconfigured/​timed-out model) turns that one
section into a deterministic fallback and leaves the other three untouched. A
fan-out that fails whole because one leg failed is worse than no fan-out at all.

Cost is measured, not hoped for: every analyst reports its token usage, the
compose step sums them, and `TOKEN_CAP_PER_REFRESH` is the budget gate a test
asserts against — fan-out multiplies calls, so this is a real limit.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .. import store
from . import butler, cost, llm, memory_recall, rollup

# ── Budget + shape constants ────────────────────────────────────────────────
ANALYST_MAX_TOKENS = 600          # output cap per analyst
CONTEXT_CHAR_BUDGET = 3500        # each analyst's brief is truncated to this
# Hard ceiling for one client's fan-out. Four analysts, each roughly
# (~900 input from a 3500-char brief + 600 output) ≈ 1500 tokens, so ~6k
# typical; the cap leaves headroom but still catches a runaway prompt.
TOKEN_CAP_PER_REFRESH = 16000

ANALYST_KEYS = ("delivery", "money", "relationship", "risk")

# Figure shapes an analyst might quote. We match anything that *looks like money
# or a percentage* and redact it unless it is a real ledger figure — a
# hallucination is by definition off-brief, so it can appear in any of these
# forms, not just the "$X" / "X%" the briefs feed. One combined pattern in a
# SINGLE pass, most-specific alternatives first, so a kept "$3,000" is consumed
# whole and its inner "3,000" is never re-scanned. 4-digit bare integers (years)
# and small counts are left alone — "since 2024" and "5 tasks" survive, while
# "$99,999", "USD 99,999", "99,999.00", "500000" and "87 percent" do not.
_FIGURE_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"                       # $99,999 / $ 99999.00
    r"|(?:USD|EUR|GBP|INR|CAD|AUD)\s?\d[\d,]*(?:\.\d+)?"  # USD 99,999
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"                 # 1,200,000  99,999.00
    r"|\d+(?:\.\d+)?\s?%"                            # 87%
    r"|\d+(?:\.\d+)?\s?percent\b"                    # 87 percent
    r"|\d{5,}(?:\.\d+)?",                            # 500000 (bare, 5+ digits)
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Analyst result ──────────────────────────────────────────────────────────
@dataclass
class AnalystResult:
    key: str
    summary: str = ""
    highlights: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    degraded: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


# ── Ground truth (the ONLY source of numbers) ───────────────────────────────
def _gather(user_id: str, client) -> dict:
    """Deterministic facts every analyst and the merge draw on. Zero LLM."""
    invoices = butler._client_invoices(user_id, client.name)
    fin = butler._financials(invoices)
    health = butler.compute_client_health(user_id, client, persist=False)
    roll = rollup.client_rollup(user_id, client.id)
    silent_days = butler._days_since(client.last_activity_at)

    # A compact, human-readable list of open blockers with their evidence, so
    # the Risk/Delivery analysts can *describe* real ones rather than invent.
    blockers: list[str] = []
    for t in roll.get("tasks", []):
        if t.get("blockerCount"):
            blockers.append(f"{t['title']}: {t['blockerCount']} blocker(s)")

    facts: list[str] = []
    try:
        from .graph_memory import query_subgraph
        sub = query_subgraph(user_id, client.name)
        facts = [f"{r['rel']}: {r['label']}" for r in sub.get("relations", [])
                 if r.get("type") == "fact"][:12]
    except Exception:
        facts = []

    # Recalled context — this is where a connected Notion (M9) reaches the
    # analysts: its ingested pages live in agent_memory (kind="notion") and
    # surface here by relevance alongside graph facts and email intel. Prose
    # only; it never contributes a number (the scrubber still guards output).
    try:
        recall_brief = memory_recall.build_recall_brief(
            user_id, f"{client.name} project status delivery blockers priorities",
            kinds=["notion", "graph_fact", "email_intel", "playbook"],
            k=5, max_chars=700,
        )
    except Exception:
        recall_brief = ""

    return {
        "client": client,
        "financials": fin,
        "health": health,
        "rollup": roll,
        "silentDays": silent_days,
        "blockers": blockers,
        "facts": facts,
        "recallBrief": recall_brief,
    }


def _fmt_money(amount) -> str:
    return f"${amount:,.0f}"


def _ground_truth_figures(ctx: dict) -> set[str]:
    """Every number an analyst is allowed to quote, in the forms it might write.

    Anything outside this set is treated as fabricated and redacted. We register
    a few textual variants (with/without `$`, with/without commas) so a correct
    figure phrased slightly differently is not falsely stripped.
    """
    allowed: set[str] = set()

    def add_money(v):
        try:
            n = float(v)
        except (TypeError, ValueError):
            return
        for s in (f"${n:,.0f}", f"${n:,.2f}", f"{n:,.0f}", f"{n:.0f}",
                  f"${n:.0f}", str(int(n)) if n == int(n) else f"{n}"):
            allowed.add(s.strip())

    def add_pct(v):
        try:
            n = int(round(float(v)))
        except (TypeError, ValueError):
            return
        allowed.add(f"{n}%")
        allowed.add(f"{n} %")

    fin = ctx["financials"]
    for k in ("invoiced", "paid", "outstanding", "overdueTotal"):
        add_money(fin.get(k))
    add_pct(ctx["rollup"].get("progressPct"))
    add_pct(ctx["health"].get("healthScore"))
    # Small integer counts are quoted bare; allow the ones we actually surface.
    for n in (fin.get("overdueCount"), ctx["rollup"].get("blockerCount"),
              ctx["rollup"].get("overdueCount"), ctx["rollup"].get("taskCount"),
              ctx["rollup"].get("storyCount"), ctx["silentDays"]):
        if isinstance(n, int):
            allowed.add(str(n))
    return allowed


def _strip_unverified_figures(text: str, allowed: set[str]) -> str:
    """Redact any currency amount or percentage not in the ground-truth set.

    The model may narrate ("payment is overdue", "delivery is slipping"); it may
    NOT introduce a figure of its own. A number it quotes is kept only if it
    matches something the ledger actually produced.
    """
    if not text:
        return text

    def repl(m: re.Match) -> str:
        tok = m.group(0).strip()
        norm = tok.replace(" ", "")
        if tok in allowed or norm in allowed:
            return tok
        return "[unverified]"

    return _FIGURE_RE.sub(repl, text)


# ── Analyst specs ───────────────────────────────────────────────────────────
def _brief_delivery(ctx: dict) -> str:
    r = ctx["rollup"]
    lines = [
        f"Delivery progress: {r['progressPct']}% across {r['taskCount']} task(s), "
        f"{r['storyCount']} story(ies).",
        f"Open blockers: {r['blockerCount']}. Overdue tasks: {r['overdueCount']}. "
        f"Stalled: {r['stalledCount']}.",
    ]
    if ctx["blockers"]:
        lines.append("Blocking items:\n- " + "\n- ".join(ctx["blockers"][:8]))
    return "\n".join(lines)


def _brief_money(ctx: dict) -> str:
    f = ctx["financials"]
    return (
        f"Invoiced {_fmt_money(f['invoiced'])}, paid {_fmt_money(f['paid'])}, "
        f"outstanding {_fmt_money(f['outstanding'])}.\n"
        f"Overdue: {f['overdueCount']} invoice(s) totalling {_fmt_money(f['overdueTotal'])}."
    )


def _brief_relationship(ctx: dict) -> str:
    silent = ctx["silentDays"]
    lines = [
        f"Days since last logged activity: {silent if silent is not None else 'unknown'}.",
        f"Health signals — risks: {'; '.join(ctx['health']['risks']) or 'none'}.",
        f"Positives: {'; '.join(ctx['health']['positiveSignals']) or 'none'}.",
    ]
    if ctx["facts"]:
        lines.append("Known relationship facts:\n- " + "\n- ".join(ctx["facts"]))
    return "\n".join(lines)


def _brief_risk(ctx: dict) -> str:
    r = ctx["rollup"]
    return (
        f"What's not going well count: {r['notGoingWellCount']}. "
        f"Blockers: {r['blockerCount']}. Overdue tasks: {r['overdueCount']}. "
        f"Stalled stories: {r['stalledCount']}.\n"
        f"Delivery health {r['score']}/100 ({r['label']}). "
        f"Overdue money: {_fmt_money(ctx['financials']['overdueTotal'])}."
    )


_SYSTEM = (
    "You are the {title} analyst on a freelancer's back-office team. You are given "
    "already-verified facts about ONE client. Write a tight, factual read of your "
    "area in JSON: {{\"summary\": \"1-2 sentences\", \"highlights\": [\"...\"], "
    "\"concerns\": [\"...\"]}}. Rules: do NOT invent numbers — refer only to figures "
    "present in the facts; if you cite a number, copy it exactly. No preamble, JSON only."
)

_SPECS = {
    "delivery": {"title": "Delivery", "brief": _brief_delivery},
    "money": {"title": "Money", "brief": _brief_money},
    "relationship": {"title": "Relationship", "brief": _brief_relationship},
    "risk": {"title": "Risk", "brief": _brief_risk},
}


def _fallback_summary(key: str, ctx: dict) -> str:
    """Deterministic, number-safe prose when the model is unavailable/failed."""
    r, f = ctx["rollup"], ctx["financials"]
    if key == "delivery":
        return f"Delivery at {r['progressPct']}% with {r['blockerCount']} open blocker(s)."
    if key == "money":
        return (f"{_fmt_money(f['outstanding'])} outstanding; "
                f"{f['overdueCount']} overdue invoice(s).")
    if key == "relationship":
        s = ctx["silentDays"]
        return f"No activity logged in {s} day(s)." if s is not None else "Activity recency unknown."
    return f"Delivery health {r['score']}/100; {r['notGoingWellCount']} concern(s) flagged."


def _run_analyst(key: str, ctx: dict, allowed: set[str], chat) -> AnalystResult:
    """Run one analyst. NEVER raises — a failure becomes a degraded section."""
    spec = _SPECS[key]
    try:
        if chat is None or not llm.is_configured():
            return AnalystResult(key=key, summary=_fallback_summary(key, ctx), degraded=True)

        brief = spec["brief"](ctx)
        # Fold in recalled context (a connected Notion, graph facts, email intel)
        # so the analyst reasons over what Kora *knows*, not just this milestone's
        # numbers. Trimmed to the per-analyst char budget.
        if ctx.get("recallBrief"):
            brief = f"{brief}\n\n{ctx['recallBrief']}"
        brief = brief[:CONTEXT_CHAR_BUDGET]
        result = chat(
            _SYSTEM.format(title=spec["title"]),
            brief,
            temperature=0.2,
            max_tokens=ANALYST_MAX_TOKENS,
            json_mode=True,
        )
        data = llm.extract_json(result.text) or {}
        summary = _strip_unverified_figures(str(data.get("summary", "")).strip(), allowed)
        highlights = [_strip_unverified_figures(str(x).strip(), allowed)
                      for x in (data.get("highlights") or [])][:5]
        concerns = [_strip_unverified_figures(str(x).strip(), allowed)
                    for x in (data.get("concerns") or [])][:5]
        return AnalystResult(
            key=key, summary=summary or _fallback_summary(key, ctx),
            highlights=highlights, concerns=concerns,
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        )
    except Exception as exc:  # isolation: this section degrades, the others don't
        return AnalystResult(key=key, summary=_fallback_summary(key, ctx),
                             degraded=True, error=str(exc)[:200])


def _section_metrics(key: str, ctx: dict) -> dict:
    """The authoritative numbers for a section — always from the ledger."""
    r, f = ctx["rollup"], ctx["financials"]
    if key == "delivery":
        return {"progressPct": r["progressPct"], "blockerCount": r["blockerCount"],
                "overdueTasks": r["overdueCount"], "stalledStories": r["stalledCount"],
                "taskCount": r["taskCount"], "storyCount": r["storyCount"]}
    if key == "money":
        return {"invoiced": f["invoiced"], "paid": f["paid"],
                "outstanding": f["outstanding"], "overdueCount": f["overdueCount"],
                "overdueTotal": f["overdueTotal"]}
    if key == "relationship":
        return {"silentDays": ctx["silentDays"],
                "risks": ctx["health"]["risks"],
                "positives": ctx["health"]["positiveSignals"]}
    return {"deliveryScore": r["score"], "deliveryLabel": r["label"],
            "notGoingWellCount": r["notGoingWellCount"], "blockerCount": r["blockerCount"]}


# ── The deterministic composer (this is the "project manager") ──────────────
def compose_client_view(user_id: str, client_id: str, *, chat=None, persist: bool = True) -> dict | None:
    """Run the fan-out and MERGE IN CODE. Returns the composed view, or None if
    the client does not exist.

    `chat` is injectable purely so tests can drive the analysts with known token
    counts and prove parallelism + isolation without a live gateway. In
    production it defaults to `llm.chat`.
    """
    client = store.get_client(user_id, client_id)
    if not client:
        return None
    if chat is None:
        chat = llm.chat

    ctx = _gather(user_id, client)
    allowed = _ground_truth_figures(ctx)

    # Fan out: the four analysts run concurrently. A barrier-based test proves
    # this is real parallelism, not a sequential loop.
    with ThreadPoolExecutor(max_workers=len(ANALYST_KEYS)) as pool:
        futures = {k: pool.submit(_run_analyst, k, ctx, allowed, chat) for k in ANALYST_KEYS}
        results = {k: fut.result() for k, fut in futures.items()}

    # ---- MERGE (pure code, no LLM) -----------------------------------------
    sections = {}
    for key in ANALYST_KEYS:
        res = results[key]
        sections[key] = {
            "metrics": _section_metrics(key, ctx),   # numbers: always from the ledger
            "summary": res.summary,                  # prose: from the analyst, figure-checked
            "highlights": res.highlights,
            "concerns": res.concerns,
            "degraded": res.degraded,
        }

    in_tok = sum(r.input_tokens for r in results.values())
    out_tok = sum(r.output_tokens for r in results.values())
    total = in_tok + out_tok
    token_cost = {
        "inputTokens": in_tok, "outputTokens": out_tok, "totalTokens": total,
        "estUsd": cost.estimate_cost_usd(in_tok, out_tok),
        "cap": TOKEN_CAP_PER_REFRESH, "withinCap": total <= TOKEN_CAP_PER_REFRESH,
    }

    view = {
        "clientId": client.id,
        "clientName": client.name,
        "headline": {
            "healthScore": ctx["health"]["healthScore"],
            "healthLabel": ctx["health"]["healthLabel"],
            "progressPct": ctx["rollup"]["progressPct"],
            "outstanding": ctx["financials"]["outstanding"],
            "openBlockers": ctx["rollup"]["blockerCount"],
        },
        "sections": sections,
        "degradedSections": [k for k in ANALYST_KEYS if results[k].degraded],
        "generatedAt": _now(),
        "stale": False,
    }

    if persist:
        try:
            store.upsert_client_view(user_id, client.id, view, token_cost, _now())
        except Exception as exc:  # pragma: no cover - cache write is best-effort
            print(f"[pm_agent] view cache write skipped: {exc}")

    return {**view, "tokenCost": token_cost}


def _deterministic_shell(user_id: str, client) -> dict:
    """A numbers-only view built with ZERO LLM — served when no cache exists yet.

    Guarantees GET never triggers a model call: a cold client still gets its
    real headline metrics and number-safe fallback prose, just flagged stale so
    the UI can offer a refresh.
    """
    ctx = _gather(user_id, client)
    allowed = _ground_truth_figures(ctx)  # noqa: F841 - kept for symmetry / future use
    sections = {
        key: {
            "metrics": _section_metrics(key, ctx),
            "summary": _fallback_summary(key, ctx),
            "highlights": [], "concerns": [], "degraded": True,
        }
        for key in ANALYST_KEYS
    }
    return {
        "clientId": client.id,
        "clientName": client.name,
        "headline": {
            "healthScore": ctx["health"]["healthScore"],
            "healthLabel": ctx["health"]["healthLabel"],
            "progressPct": ctx["rollup"]["progressPct"],
            "outstanding": ctx["financials"]["outstanding"],
            "openBlockers": ctx["rollup"]["blockerCount"],
        },
        "sections": sections,
        "degradedSections": list(ANALYST_KEYS),
        "generatedAt": None,
        "stale": True,
    }


def get_client_view(user_id: str, client_id: str) -> dict | None:
    """Serve the cached view. ZERO LLM calls (invariant client_view_refresh_is_cached).

    Cache miss returns a deterministic shell — still no model call — rather than
    silently composing, so a page load can never surprise-bill the user.
    """
    client = store.get_client(user_id, client_id)
    if not client:
        return None
    try:
        cached = store.get_client_view(user_id, client_id)
    except Exception as exc:
        # A missing cache table (migration not yet applied) or a transient read
        # error must never fault a page load — fall back to the deterministic
        # shell, exactly as a cold cache does.
        print(f"[pm_agent] view cache read skipped: {exc}")
        cached = None
    if cached and cached.get("view"):
        return {**cached["view"], "tokenCost": cached.get("token_cost") or {},
                "refreshedAt": cached.get("refreshed_at")}
    return _deterministic_shell(user_id, client)


def refresh_all_views(user_id: str, *, chat=None) -> dict:
    """Recompose every client's view — the nightly cron entry point."""
    refreshed, tokens = 0, 0
    for c in store.list_clients(user_id):
        view = compose_client_view(user_id, c.id, chat=chat)
        if view:
            refreshed += 1
            tokens += view["tokenCost"]["totalTokens"]
    return {"ok": True, "clientsRefreshed": refreshed, "totalTokens": tokens}
