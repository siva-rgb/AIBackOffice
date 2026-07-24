# ADR 0001 — Agent-maintained work hierarchy and PM fan-out

- **Date:** 2026-07-23
- **Status:** **accepted** (2026-07-23 — all three forks resolved by the user; see "Resolved forks")
- **Phase / milestone:** route at L1; spans the M1–M4 arc

## Context

The user wants Notion-like granularity — **Client → Project → Task → Story** — where each story carries
qualitative signal (progress, blockers, what's going well, what isn't), rolling up into project health
and client status. Alongside it: client-level payment discussion, general discussion, meeting
scheduling and key notes. Critically, **the agent maintains all of it** by gathering from email,
meetings, Drive and user input, fanning out subagents "like a team of humans would."

G0 Existence Pre-Flight (2026-07-23) found **three of the four levels already exist**:
`Client` ✅, `Engagement` ✅ (= Project: status, dates, budget, `value_delivered`), `Task` ✅
(client + engagement linked, auto-capture, Notion mirror). `Story` is **unbuilt** (zero hits).
`ClientNote.note_type` already spans `meeting|call|email|decision|blocker|update|general`, meeting
scheduling exists via HITL `create_calendar_event`, and payment discussion exists via invoices +
email `financial_mentions`.

So the tension is not "build a PM tool" — most of the skeleton is there. The real gaps are the
**story layer**, the **qualitative status model**, the **roll-up computation** (today
`compute_client_health` reads invoices/engagements/silence but **not work progress**), and the
**orchestration** that keeps it all current without the user typing.

The standing product rule (`PLAN.md`, Re-plan 2026-07-23) is: *can the agent maintain this surface
without the user typing?* A four-level hierarchy passes that rule **only if** every qualitative field
is agent-fillable from evidence. Otherwise it degenerates into empty containers the user must fill —
precisely the Notion failure mode this feature is meant to beat.

## Decision

**Extend the existing `Client → Engagement → Task` spine with a `Story` level and an evidence-backed
qualitative status model, compute health as a deterministic bottom-up roll-up, and maintain it with a
bounded fan-out of role-scoped LLM analysts whose outputs are merged deterministically.**

Four load-bearing constraints:

1. **Extend, never rebuild.** `Engagement` *is* the Project level; `Task` stays as-is. Story is a new
   child of Task. No parallel hierarchy.
2. **Every qualitative field carries provenance.** `going_well` / `not_going_well` / `blockers` each
   record the source (`email` / `meeting` / `drive` / `user` / `agent`) and a reference to the
   originating record. A field with no evidence is left empty rather than invented.
3. **Roll-up is deterministic, never model-authored.** Story → Task → Project → Client health is
   arithmetic over real state (progress %, blocker count, overdue, staleness). The LLM may *narrate*
   the roll-up; it may never *compute* it. This mirrors the existing briefing pattern where figures
   are deterministic and validated.
4. **Fan-out means parallel role-scoped calls with a deterministic merge** — Delivery, Money,
   Relationship and Risk analysts, each with a narrow tool subset, synthesized by code. Not
   free-running autonomous agents.

## Consequences

- **Positive:** answers "why not Notion" concretely — the hierarchy fills itself from Gmail/meetings/
  Drive. Reuses the whole existing spine (engagements, tasks, notes, graph, semantic recall,
  auto-capture) rather than duplicating it. Roll-up health finally reflects *delivery*, not just money.
- **Positive:** bounded, debuggable orchestration — each analyst is independently testable, and the
  merge is code, so a bad LLM response degrades one section instead of corrupting the client view.
- **Negative / cost:** a fourth hierarchy level is real UI and API surface, and is heavy for the
  target user (freelancer, ~4 clients). Concern was raised and the user reaffirmed; proceeding.
- **Negative / cost:** fan-out multiplies LLM calls per refresh. Must be cached and scheduled, never
  run synchronously on page load. Token budget per client refresh has to be capped and measured.
- **Risk to watch:** qualitative fields going stale. Mitigation — every field is timestamped with its
  evidence; the UI shows staleness rather than presenting an old judgement as current.
- **Invariants proposed for `context-graph.json`:**
  - `rollup_health_is_deterministic` — no health/progress number originates from an LLM response.
  - `qualitative_fields_carry_provenance` — `going_well`/`not_going_well`/`blockers` rows without a
    source reference are not persisted.
  - `client_view_refresh_is_cached` — the composed view is never regenerated synchronously on GET.

## Alternatives rejected

- **Build a Notion-style block editor / generic databases.** Enormous cost, zero differentiation, and
  it fails the product rule — the user fills it, not the agent.
- **Story as a 4th user-maintained container only.** Rejected as the *sole* framing; the level is
  being built, but its value comes from agent-authored qualitative status, not from another empty box.
- **Autonomous multi-agent team with free-running goals.** Rejected for reliability and cost, and
  because these agents write to real client records — blast radius is too high without a deterministic
  merge and the existing HITL gates.
- **Replacing `Engagement` with a new `Project` entity.** Rejected — pure churn; `Engagement` already
  carries status, dates, budget and contract/proposal links, and tasks already reference it.

## Resolved forks (2026-07-23)

1. **Story semantics → durable work item under Task.** A real entity with title, status and
   `progress_pct`, carrying its own `going_well` / `not_going_well` / `blockers`. Renders as a tree;
   assignable and trackable as a unit. (Rejected: append-only progress stream; entity + stream hybrid.)
2. **Authorship → agent authors, user may override.** The agent fills qualitative fields from
   email/meeting/Drive evidence with provenance. A user edit sets `user_edited = true` on that entry,
   and **subsequent agent refreshes must not overwrite it** — they may append a new observation
   alongside, never silently replace a human judgement. This is the compromise that keeps the surface
   self-filling without making it unfalsifiable.
3. **Refresh cadence → nightly cron + on-demand button.** Composition is scheduled (alongside the
   existing pre-dawn gmail/graph/memory jobs) and manually forceable. **Never** synchronous on GET.
   Cost is therefore bounded per client per day and measurable.

### Derived invariant (add to `context-graph.json` in M1)
- `user_override_survives_agent_refresh` — an entry with `user_edited = true` is never mutated or
  deleted by a fan-out refresh.
