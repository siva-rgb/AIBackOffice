# Kora — Agent Architecture & Gap Tracker

> Last updated: 2026-06-27
> Status key: ✅ done · 🟡 partial · ⬜ not started

---

## 1. Agent Inventory

### 1.1 LLM-Powered Agents

| Agent | File | Entry Point(s) | What it does | LLM calls |
|---|---|---|---|---|
| **Supervisor** | `services/supervisor.py` | `run_supervisor()`, `chat_agentic()`, `chat()` | Full orchestration pass: reconcile → assess → queue → brief. Also handles multi-turn tool-calling chat with HITL approval queue. | `compose_manager_briefing()`, `chat_reply()`, tool-calling loop (≤5 turns) |
| **Butler** | `services/butler.py` | `generate_morning_briefing()`, `parse_capture()` | Client relationship intelligence. Morning brief + freeform capture parsing (extracts client, note, status update). | `compose_butler_briefing()`, `parse_capture()` |
| **Invoice Follow-up** | `services/invoice_agent.py` | `run_follow_up_agent()`, `send_follow_up_for()` | 3-attempt reminder cadence on overdue invoices. Drafts personalised follow-up emails per invoice. | `draft_follow_up_email()` per invoice |
| **Invoice Demand** | `services/invoice_agent.py` | `generate_demand_letter()` | Formal demand letter grounded in the signed contract's payment clause. | `draft_demand_letter()` |
| **Contract Generator** | `services/contract_agent.py` | `generate_contract()` | AI-drafts contract from wizard inputs + jurisdiction clause library. Auto-reviews on generation. | `generate_contract()` + `review_contract()` |
| **Contract Reviewer** | `services/contract_agent.py` | `review_contract()` | Reviews a received/pasted contract for risk flags. | `review_contract()` |
| **Proposal Generator** | `services/proposal_agent.py` | `generate_proposal()`, `proposal_to_contract()` | Generates proposals; accept path auto-generates a matching contract. | `generate_proposal()` |
| **Meeting Agent** | `services/meeting_agent.py` | `process_transcript()` | Processes meeting transcript → MOM, action items, commitment extraction. Queues follow-up email. | `extract_meeting_mom()` |
| **Bookkeeper** | `services/bookkeeper.py` | `ingest_transactions()`, `recategorize_uncategorized()` | Batch-categorises CSV transactions with playbook corrections applied first. | `categorize_transactions()` per 50-row batch |
| **Cashflow Forecaster** | `services/cashflow_agent.py` | `compute_forecast()` | 3-scenario 90-day projection + LLM-generated risks and recommended actions. | `generate_cashflow_insights()` (optional) |
| **Alert Generator** | `services/alert_agent.py` | `run_digest()` | Snapshot financial state → ask LLM for proactive alerts → dedupe → insert. | `generate_alerts()` |
| **Gmail Intel** | `services/gmail_intel.py` | `sync_client_email_intel()` | Syncs Gmail threads per client; extracts sentiment, action_needed, financial mentions. | Thread analysis calls |

---

### 1.2 Deterministic Agents (no LLM)

| Agent | File | What it does |
|---|---|---|
| **Cross-Module Triggers** | `services/cross_module.py` | Contract signed → create invoices. Payment reconciliation (amount + client-name token matching). |
| **Drive Intel** | `services/drive_intel.py` | Scans Kora Drive folder; classifies + routes files (regex-based, no LLM). |
| **Calendar Intel** | `services/calendar_intel.py` | Read-only calendar queries: today's meetings, unlogged past meetings, availability slots. |
| **Gmail Agent (executor)** | `services/gmail_agent.py` | Executes HITL-approved email sends via Gmail API. |
| **Calendar Agent (executor)** | `services/calendar_agent.py` | Executes HITL-approved calendar event creation (with Meet link). |
| **Playbook** | `services/playbook.py` | Passively observes user decisions, corrections, email edits, payments. Assembles learned context for LLM prompts. |

---

### 1.3 Infrastructure Services

| Service | Purpose |
|---|---|
| `services/llm.py` | Single HTTP client wrapping the OpenAI-compatible gateway. All LLM calls funnel through here. |
| `services/vertex_ai.py` | Provider abstraction: `get_ai()` returns `RealLLMProvider` or `MockGemini` based on `KORA_AI_BACKEND`. |
| `services/agent_logger.py` | Audit trail for every agent action (cost, tokens, latency, outcome). |
| `services/validation.py` | Post-generation hallucination check (unknown amounts/entities in briefings and emails). |

---

## 2. Agent Flow Map

### Flow A — Supervisor Pass (manual or cron)

```
POST /api/manager/run
  └─ supervisor.run_supervisor()
       ├─ cross_module.reconcile_payments()          [deterministic]
       ├─ bookkeeper.recategorize_uncategorized()     [LLM batch]
       ├─ gather_state()                              [DB reads]
       ├─ assess()                                    [deterministic rules]
       │    ├─ flag invoices: soft_followup / demand / writeoff
       │    └─ flag cashflow: danger / ok
       ├─ queue_tasks() → ManagerTask rows            [HITL gate]
       ├─ ai.compose_manager_briefing()               [1 LLM call]
       └─ persist manager_memory JSONB
```

### Flow B — Butler Morning Briefing (manual or cron)

```
POST /api/butler/run
  └─ butler.generate_morning_briefing()
       ├─ list_clients_enriched()                    [DB reads]
       ├─ compute_client_health() × N clients        [deterministic]
       ├─ calendar_intel.get_todays_meetings()        [Google API]
       ├─ playbook.assemble_context()                 [DB reads]
       ├─ ai.compose_butler_briefing()                [1 LLM call]
       ├─ validation.validate_briefing()              [hallucination check]
       └─ insert alert(morning_briefing) + butler_memory
```

### Flow C — Contract Signed → Invoices

```
PATCH /api/contracts/{id}/status  { status: "signed" }
  └─ cross_module.on_contract_signed()
       ├─ parse milestones from contract.terms         [deterministic]
       ├─ insert invoices (one per milestone)
       ├─ insert alert(contract_signed)
       └─ log_action(cross_module, contract_signed)
```

### Flow D — Invoice Follow-up Campaign (cron)

```
POST /api/invoices/run-follow-ups
  └─ invoice_agent.run_follow_up_agent()
       ├─ cross_module.reconcile_payments()           [deterministic]
       └─ for each overdue invoice on schedule:
            ├─ ai.draft_follow_up_email()             [1 LLM call per invoice]
            ├─ update invoice (follow_up_count++, status → "overdue")
            └─ log_action(invoice_agent, follow_up_sent)
```

### Flow E — Manager Task Approval (HITL)

```
POST /api/manager/tasks/{id}/approve
  └─ supervisor.approve_task()
       ├─ send_followup      → invoice_agent.send_follow_up_for()
       ├─ send_demand        → invoice_agent.generate_demand_letter()
       ├─ writeoff_invoice   → mark invoice cancelled
       ├─ send_email_gmail   → gmail_agent.execute_gmail_send()
       ├─ create_calendar_event → calendar_agent.execute_calendar_event()
       └─ send_proposal      → mark proposal "sent"
            └─ playbook.observe_decision()
```

### Flow F — Agentic Chat (tool-calling loop)

```
POST /api/manager/chat
  └─ supervisor.chat_agentic()
       └─ ≤5 turn loop:
            ├─ LLM decides tool to call
            ├─ read tools     → auto-execute (get_invoice, list_clients, …)
            └─ action tools   → queue ManagerTask for HITL (send_email, propose_writeoff, …)
```

### Flow G — CSV Upload → Categorise + Reconcile

```
POST /api/bookkeeping/upload-csv
  └─ bookkeeper.ingest_transactions()
       ├─ playbook.apply_corrections_before_llm()    [permanent overrides]
       ├─ ai.categorize_transactions() × batches     [LLM per 50 rows]
       └─ cross_module.reconcile_payments()          [match income → invoices]
```

### Flow H — Quick Capture → Notes

```
POST /api/butler/captures
  └─ butler.parse_capture()
       ├─ ai.parse_capture()                         [1 LLM call]
       ├─ if client found + note:  insert client_note, touch last_activity_at
       └─ if high confidence + status_update:  update engagement status
```

### Flow I — Meeting Transcript → MOM

```
POST /api/meetings/upload-transcript
  └─ meeting_agent.process_transcript()              [background task]
       ├─ ai.extract_meeting_mom()                   [1 LLM call]
       ├─ update meeting record (summary, action_items)
       ├─ playbook.observe_meeting()
       └─ if commitments detected: queue follow-up email task
```

---

## 3. Agent Gaps — What Does NOT Exist Today

---

### Gap 1 — No Agent-to-Agent Chaining ✅

**Status:** Each agent fires independently. No agent reads another agent's output.

| Current behaviour | Target behaviour |
|---|---|
| Contract signed → user manually creates invoices | Contract signed → invoice agent fires automatically |
| Supervisor briefing runs → butler has no awareness | Butler brief includes supervisor's latest advisory |
| Invoice 30 days overdue → nothing happens | Invoice agent detects overdue → queues follow-up automatically |
| Cashflow forecast is static | After reconciliation → forecast auto-refreshes |

**What needs to be built:**

- Extend `cross_module.py` with new trigger functions:
  - `on_invoice_overdue(user_id, invoice_id)` — auto-queue demand after N days with no payment
  - `on_reconciliation_done(user_id, result)` — trigger cashflow refresh + supervisor mini-pass
  - `on_supervisor_run(user_id, advisories)` — write advisories to butler_memory so butler reads them
- Wire these calls into the end of existing agent functions (no new framework needed)

**Files to change:** `cross_module.py`, `supervisor.py`, `cashflow_agent.py`, `butler.py`

---

### Gap 2 — No Memory Between Agent Runs ✅

**Status:** Every supervisor run starts from zero. `manager_memory` JSONB exists but only stores the last briefing text, not structured escalation state.

| Current behaviour | Target behaviour |
|---|---|
| Soft follow-up sent → supervisor sends another soft follow-up next run | Supervisor reads: "2 soft follow-ups, no response → escalate to demand" |
| Butler doesn't know you chased 3 clients this week | Butler says "you've already followed up with Acme twice, consider holding off" |
| Forecast ignores payment pattern history | Forecast notes "this client typically pays 15 days late" from prior runs |

**What needs to be built:**

- Extend `manager_memory` schema:
  ```json
  {
    "escalation_state": {
      "<client_id>": { "followups_sent": 2, "last_action": "soft_followup", "next": "demand" }
    },
    "payment_patterns": {
      "<client_id>": { "avg_days_late": 14, "sample_size": 6 }
    },
    "last_run": "2026-06-27"
  }
  ```
- `supervisor.run_supervisor()`: read escalation_state at start, use to choose demand vs soft follow-up, write updated state at end
- `butler.generate_morning_briefing()`: read escalation_state to include recent chase activity in brief
- `cashflow_agent.compute_forecast()`: read payment_patterns to adjust expected collection dates

**Files to change:** `supervisor.py`, `butler.py`, `cashflow_agent.py`

---

### Gap 3 — No Autonomous Scheduled Triggers ✅ (highest impact)

**Status:** Cron endpoints exist and are secured with `CRON_SECRET`. The external scheduler pointing at them does not exist.

**What doesn't fire automatically today:**
- No daily supervisor pass → no automatic overdue detection, no daily briefing
- No morning butler briefing email to the user
- No "invoice 30 days overdue → auto-queue demand" reaction
- No weekly cashflow report
- No "contract expiring in 7 days" alert

**What needs to be configured (zero new Python code):**

Option A — GCP Cloud Scheduler (recommended for production):
```yaml
# cloud-scheduler.yaml
jobs:
  - name: kora-supervisor-daily
    schedule: "0 7 * * *"          # 7am daily
    httpTarget:
      uri: https://<your-cloud-run-url>/api/manager/run
      httpMethod: POST
      headers:
        x-cron-secret: <CRON_SECRET>

  - name: kora-butler-morning
    schedule: "0 8 * * 1-5"        # 8am Mon–Fri
    httpTarget:
      uri: https://<your-cloud-run-url>/api/butler/run
      httpMethod: POST
      headers:
        x-cron-secret: <CRON_SECRET>

  - name: kora-invoice-followups
    schedule: "0 9 * * 1-5"        # 9am Mon–Fri
    httpTarget:
      uri: https://<your-cloud-run-url>/api/invoices/run-follow-ups
      httpMethod: POST
      headers:
        x-cron-secret: <CRON_SECRET>
```

Option B — Vercel Cron (if frontend on Vercel):
```json
// vercel.json
{
  "crons": [
    { "path": "/api/cron/supervisor", "schedule": "0 7 * * *" },
    { "path": "/api/cron/butler",     "schedule": "0 8 * * 1-5" }
  ]
}
```

Option C — GitHub Actions (free, zero infra):
```yaml
# .github/workflows/cron.yml
on:
  schedule:
    - cron: '0 7 * * *'
jobs:
  supervisor:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -s -X POST ${{ secrets.API_URL }}/api/manager/run \
            -H "x-cron-secret: ${{ secrets.CRON_SECRET }}"
```

**Tracking note:** This is a prerequisite for Gap 1 (chaining) and Gap 2 (memory) to have real-world value.

---

### Gap 4 — No Retry / Fallback Between Agents ✅

**Status:** If any sub-step inside `run_supervisor()` throws, the entire pass either crashes or silently returns an empty advisory. The LLM briefing call has `tenacity` retry on 429/5xx but structured sub-agent failures are not handled.

| Failure scenario | Current result | Target result |
|---|---|---|
| LLM briefing call times out | `status_line` is empty, user sees blank manager panel | Partial result returned: "Briefing unavailable — rule-based tasks still queued" |
| `reconcile_payments()` DB error | Supervisor pass fails before any tasks are queued | Skip reconciliation, continue with assess() |
| `cashflow_agent.compute_forecast()` errors | Entire gather_state fails | Catch, continue with empty cashflow data, flag in briefing |

**What needs to be built:**

- Wrap each sub-step in `run_supervisor()` with structured try/except:
  ```python
  try:
      reconcile_result = await cross_module.reconcile_payments(user_id)
  except Exception as e:
      logger.warning("reconcile failed: %s — skipping", e)
      reconcile_result = {"matched": 0}
      state["partial_failure"] = True
  ```
- Add `partial_failure` flag to briefing context so LLM can mention it
- Return `{"status": "partial", "failed_steps": [...]}` in the API response instead of 500

**Files to change:** `supervisor.py` (3–4 try/except blocks around sub-steps)

---

## 4. LangGraph / LangChain — Deferred Decision

> **Not implementing now. Documented here for future reference.**

### Why it was considered

The gaps above (agent chaining, memory, retry/fallback) are exactly the problems LangGraph was built for:
- **Agent-to-agent chaining** → LangGraph nodes with directed edges
- **Memory between runs** → LangGraph `MemorySaver` / `SqliteSaver` checkpointers
- **Retry/fallback** → LangGraph node error handlers + conditional re-routing
- **Multi-turn tool calling** → LangGraph `ToolNode` + `MessagesState`

### Why it is not needed now

Kora's orchestration is a **linear pipeline with deterministic routing**. The trigger logic (`if invoice.days_overdue > 30 → demand`) does not branch at runtime based on LLM decisions. Adding LangGraph would replace ~100 lines of clear Python with ~500 lines of graph definition.

### When to revisit

Revisit LangGraph when **any** of these become true:

1. **Non-deterministic routing** — an LLM decides which of N agents fires next (not a rules-based if/else)
2. **Long-running pause + resume** — an agent needs to pause mid-workflow, wait for human input, and resume across separate HTTP requests
3. **5+ agents in a chain** — the linear-pipeline mental model breaks down and a graph is genuinely clearer
4. **Agent-to-agent feedback loops** — agent A reviews agent B's output and sends it back for revision (cycle in the graph)

### Migration path (when ready)

```
llm.py / vertex_ai.py  →  keep as-is (LangChain ChatModel wraps any OpenAI-compatible endpoint)
supervisor.run_supervisor()  →  LangGraph StateGraph with 6 nodes
butler, invoice, contract agents  →  LangGraph ToolNodes
cross_module triggers  →  LangGraph conditional edges
manager_memory  →  LangGraph SqliteSaver / SupabaseSaver checkpointer
```

LangChain adds value primarily as a **prompt template manager** (structured prompt versioning) and **callback system** (token cost tracking). Neither is a blocker for current development.

---

## 5. Implementation Priority

| # | Gap | Effort | Impact | Status |
|---|---|---|---|---|
| 1 | Autonomous scheduled triggers (Gap 3) | XS — config only | Highest — turns Kora into a proactive system | ✅ `.github/workflows/cron.yml`, `artifacts/cloud-scheduler.yaml` |
| 2 | Retry/fallback in supervisor (Gap 4) | S — 4 try/except blocks | Medium — prevents silent failures | ✅ `supervisor.py` — `failed_steps`, degraded response on state failure |
| 3 | Memory between runs (Gap 2) | M — extend manager_memory schema + 3 read/write points | High — enables escalation | ✅ `supervisor.py` escalationState + paymentPatterns; `butler.py` reads; `cashflow_agent.py` adjusts dates |
| 4 | Agent-to-agent chaining (Gap 1) | M — 3–4 new cross_module functions + wiring | High — closes the automation loop | ✅ `cross_module.py` — `on_reconciliation_done`, `on_supervisor_run`, `on_invoice_demand_sent` |
| 5 | LangGraph migration | XL | Future — only if non-deterministic routing needed | Deferred |
