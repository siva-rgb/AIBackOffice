# Butler — Frontend Reference

Stack: Next.js 14 (App Router), TypeScript, Tailwind CSS, Shadcn/ui.
Follow all rules in main SKILL.md §9. These are Butler-specific additions only.

---

## New routes

```
/butler                         — Butler home: briefing + client list + quick capture
/butler/clients                 — Full client list (also accessible from sidebar)
/butler/clients/new             — Add client wizard
/butler/clients/[clientId]      — Client workspace (tabs: Overview / Engagements / Notes / Financials)
/butler/clients/[clientId]/engagements/new  — Add engagement
/butler/proposals               — Proposal list
/butler/proposals/new           — Proposal generator wizard
/butler/proposals/[proposalId]  — Proposal detail + send/accept actions
/butler/retainers               — Retainer list
/butler/retainers/new           — Add retainer form
/butler/capture                 — Quick capture review queue (low-confidence items)
```

---

## Sidebar addition

Add "Butler" above "Bookkeeping" in the sidebar nav. Icon: `ti-robot`.

```tsx
// In the sidebar nav array, insert before bookkeeping:
{
  label: "Butler",
  href: "/butler",
  icon: "ti-robot",
  badge: pendingCaptureCount > 0 ? pendingCaptureCount : undefined
}
```

The badge shows the count of quick captures needing review. Fetch with:
`GET /api/captures/review` → count of items with `requires_review: true`.

---

## Quick capture component

This is the most important UX element. Must be:
- Always one click / one tap away from anywhere in the app
- Accepts freeform text — no structure required from the user
- Submits and returns to previous context in < 3 seconds

```tsx
// components/butler/QuickCapture.tsx
// Floating input bar fixed to bottom of screen (below main content, above mobile nav)
// On desktop: persistent text field with "Tell Kora something..." placeholder
// On mobile: floating button (ti-message-plus) that expands to text input

"use client"
import { useState } from "react"
import { apiPost } from "@/lib/api/client"

export function QuickCapture() {
  const [text, setText] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  async function submit() {
    if (!text.trim() || submitting) return
    setSubmitting(true)
    try {
      await apiPost("/captures", { text: text.trim(), source: "web" })
      setText("")
      setSubmitted(true)
      setTimeout(() => setSubmitted(false), 2000)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 border-t bg-background px-4 py-3 z-40">
      <div className="max-w-4xl mx-auto flex gap-2">
        <input
          type="text"
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => e.key === "Enter" && submit()}
          placeholder={submitted ? "Got it." : "Tell Kora something... (e.g. 'Finished the Harbor Design draft')"}
          className="flex-1 rounded-lg border bg-background px-3 py-2 text-sm
                     focus:outline-none focus:ring-2 focus:ring-ring"
          maxLength={2000}
          disabled={submitting}
        />
        <button
          onClick={submit}
          disabled={!text.trim() || submitting}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium
                     text-primary-foreground disabled:opacity-50"
        >
          {submitting ? "..." : "Log"}
        </button>
      </div>
    </div>
  )
}
```

---

## Butler home page (`/butler/page.tsx`)

Layout (top to bottom):
1. Morning briefing card
2. Quick stats row (4 numbers)
3. Client list with health indicators
4. Quick capture review queue (if items pending)

```tsx
// app/(dashboard)/butler/page.tsx
import { apiGet } from "@/lib/api/client"

export default async function ButlerPage() {
  const [butlerState, clients] = await Promise.all([
    apiGet("/butler"),
    apiGet("/clients?status=active")
  ])

  return (
    <div className="space-y-6 pb-20"> {/* pb-20 for QuickCapture bar */}
      <MorningBriefingCard briefing={butlerState.last_briefing} memory={butlerState.memory} />
      <ButlerStatsRow clients={clients} />
      <ClientHealthList clients={clients} />
      <CaptureReviewQueue />
    </div>
  )
}
```

### Morning briefing card

```tsx
// components/butler/MorningBriefingCard.tsx
// Shows: headline (large), summary (2 sentences), focus today (checklist style),
//        going_well + watch_out in two muted columns at bottom
// "Run now" button → POST /butler/run → refreshes page
// Tone indicator: green dot (energetic), gray dot (steady), amber dot (cautious)

// If no briefing yet (new user):
// Empty state: "Your morning briefing will appear here each day at 7am.
//              Run it now to see your first one." + "Run butler" button
```

### Client health list

```tsx
// components/butler/ClientHealthList.tsx
// Table rows: [health dot] [client name] [status badge] [active engagements count]
//             [outstanding amount] [last activity]
// Health dot: green (≥75), amber (50-74), red (<50)
// Clicking row → /butler/clients/[clientId]
// "Add client" button top right

// Health dot component:
function HealthDot({ score }: { score: number }) {
  const color = score >= 75 ? "bg-green-500" : score >= 50 ? "bg-amber-500" : "bg-red-500"
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
}
```

---

## Client workspace page (`/butler/clients/[clientId]/page.tsx`)

```tsx
// Header section (always visible):
// [Client name] [Status badge] [Health score chip] [Edit button]
// Row: [what_we_do text] [Client type chip] [Industry]
// Financials row: [$X invoiced] [$X paid] [$X outstanding]
//
// Tab content (use URL-based tabs, not state — for deep linking):
// /butler/clients/[clientId]              → Overview tab
// /butler/clients/[clientId]?tab=engagements → Engagements
// /butler/clients/[clientId]?tab=notes   → Notes
// /butler/clients/[clientId]?tab=financials → Financials

// OVERVIEW tab:
// AI briefing card for this client (from health_agent output)
// Recent notes (last 5, with "Add note" inline)
// Active engagements summary (status + last update)

// ENGAGEMENTS tab:
// List: [title] [status badge] [progress] [target date] [value]
// Status badge colors: active=blue, on_track=green, at_risk=amber, done=gray, paused=gray
// "Add engagement" button → inline form (no new page needed for simple add)

// NOTES tab:
// Chronological feed of client_notes
// Note type icons: ti-users (meeting), ti-phone (call), ti-mail (email),
//                  ti-alert-triangle (blocker), ti-check (decision), ti-edit (update)
// "Add note" → simple textarea + type selector

// FINANCIALS tab:
// List of linked invoices, contracts, proposals, retainers for this client
// Totals: all-time invoiced, collected, outstanding
// "Create invoice for this client" → pre-fills client fields
```

---

## Add client wizard (`/butler/clients/new/page.tsx`)

Three steps. Minimal — don't overwhelm new users.

```
Step 1: Who is this client?
  - Client name (required)
  - Email (optional)
  - Company (optional)
  - Client type (individual / company / agency / marketplace) — pill buttons

Step 2: What do you do for them?
  - what_we_do text field: "Describe in one sentence what you do for them"
  - Industry (optional dropdown: Design, Development, Writing, Marketing,
    Consulting, E-commerce, Other)
  - Currency (if different from your default)

Step 3: Connect existing records (optional, auto-run in background)
  - "We found X invoices and Y contracts with this client name. Link them?"
  - Yes → runs backfill for this client only
  - Skip → proceed
  - Shows which records will be linked

After step 3: Land on /butler/clients/[newClientId] (Overview tab)
```

---

## Proposal generator wizard (`/butler/proposals/new/page.tsx`)

```
Step 1: Client + title
  - Select existing client OR enter new client name + email
  - Proposal title

Step 2: Scope and deliverables
  - Scope description: large textarea, 2000 char limit
    Placeholder: "What will you do for this client? Describe the work in plain English."
  - Deliverables: textarea
    Placeholder: "List the specific outputs they'll receive. One per line is fine."
  - Timeline: shorter textarea
    Placeholder: "e.g. '4 weeks from kickoff, with weekly check-ins'"

Step 3: Investment
  - Total amount (number field)
  - Currency (default from user profile)
  - Pricing type: fixed / hourly / retainer / milestone (pill buttons)
  - Payment terms (text, pre-filled with "50% upfront, 50% on completion")
  - Valid for: 30 days (dropdown: 14 / 30 / 60 / 90)

Step 4: AI generation
  - "Generate proposal" button → POST /proposals/generate
  - Show spinner: "Writing your proposal..."
  - On success: render generated markdown in review UI
  - Show clause explanations in a collapsible sidebar (same pattern as contract reviewer)
  - "Looks good" → saves as draft → redirect to /butler/proposals/[id]
  - "Edit" → back to step 2/3 with fields pre-filled
  - "Regenerate" → re-calls the API

Step 5 (on proposal detail page, not wizard):
  - Download PDF
  - Send to client (→ queues as manager_task for HITL approval)
  - Mark as accepted (→ auto-generates contract)
```

---

## Retainer form (`/butler/retainers/new/page.tsx`)

Single page, not a wizard — retainers are simple.

```
Fields:
  - Client (select existing or enter name)
  - Title: "What is this retainer for?" e.g. "Monthly SEO"
  - Amount + currency
  - Billing cycle: weekly / monthly / quarterly / annual (pill buttons)
  - Start date
  - End date (optional — leave blank for ongoing)
  - Auto-create invoice: toggle (default on)
    Helper text: "When on, Kora creates a draft invoice automatically on each billing date"
  - Renewal reminder: toggle (default on)
    Helper text: "Kora alerts you 30 days before the end date"

Submit → POST /retainers → redirect to /butler/retainers
```

---

## Empty states

Each page needs a non-clinical empty state. Tone: motivating, specific, honest.

```
/butler (no clients yet):
  Icon: ti-robot (large, muted)
  Title: "Kora is ready — add your first client"
  Body: "Once you add a client, Kora monitors the relationship for you.
         It will flag overdue invoices, stalled work, and long silences
         before they become problems."
  CTA: "Add first client"

/butler/clients (empty):
  Same as above.

/butler/clients/[id] Engagements tab (no engagements):
  Icon: ti-briefcase
  Title: "No active engagements"
  Body: "Add an engagement to help Kora understand what work is happening
         for this client. One sentence is enough — you can always add more detail later."
  CTA: "Add engagement"

/butler/clients/[id] Notes tab (no notes):
  Icon: ti-notes
  Title: "No notes yet"
  Body: "Use quick capture at the bottom of the screen to log anything
         about this client. Kora will organize it automatically."

/butler/proposals (no proposals):
  Icon: ti-file-description
  Title: "Proposals close deals before a contract exists"
  Body: "Generate a professional proposal in 2 minutes.
         When the client accepts, Kora turns it into a contract automatically."
  CTA: "Create first proposal"

/butler/retainers (no retainers):
  Icon: ti-repeat
  Title: "Retainers make your cash flow predictable"
  Body: "Add a retainer and Kora creates your invoice automatically
         on each billing date. It also uses retainer income to make
         your 90-day cash flow forecast much more accurate."
  CTA: "Add a retainer"

/butler/capture (nothing to review):
  Icon: ti-check
  Title: "Everything looks good"
  Body: "Quick captures Kora isn't sure about will appear here for your review.
         Right now there's nothing to check."
```

---

## API client additions (`lib/api/client.ts`)

Add typed wrappers alongside existing `apiGet` / `apiPost`:

```typescript
// Clients
export const clientsApi = {
  list: (status?: string) => apiGet<Client[]>(`/clients${status ? `?status=${status}` : ""}`),
  get: (id: string) => apiGet<ClientDetail>(`/clients/${id}`),
  create: (body: ClientCreate) => apiPost<Client>("/clients", body),
  update: (id: string, body: Partial<ClientCreate>) => apiPatch<Client>(`/clients/${id}`, body),
  engagements: (clientId: string) => apiGet<Engagement[]>(`/clients/${clientId}/engagements`),
  notes: (clientId: string) => apiGet<ClientNote[]>(`/clients/${clientId}/notes`),
}

// Butler
export const butlerApi = {
  getState: () => apiGet<ButlerState>("/butler"),
  run: () => apiPost<Briefing>("/butler/run", {}),
  refreshHealth: (clientId: string) => apiPost(`/butler/clients/${clientId}/health`, {}),
}

// Captures
export const capturesApi = {
  submit: (text: string) => apiPost<{id: string, status: string}>("/captures", { text, source: "web" }),
  reviewQueue: () => apiGet<QuickCapture[]>("/captures/review"),
}

// Proposals
export const proposalsApi = {
  list: () => apiGet<Proposal[]>("/proposals"),
  generate: (body: ProposalGenerateRequest) => apiPost<Proposal>("/proposals/generate", body),
  accept: (id: string) => apiPost(`/proposals/${id}/accept`, {}),
  send: (id: string) => apiPost(`/proposals/${id}/send`, {}),
}

// Retainers
export const retainersApi = {
  list: () => apiGet<Retainer[]>("/retainers"),
  create: (body: RetainerCreate) => apiPost<Retainer>("/retainers", body),
}
```

---

## TypeScript types (`types/butler.ts`)

```typescript
export interface Client {
  id: string
  name: string
  email?: string
  company?: string
  client_type: "individual" | "company" | "agency" | "marketplace"
  status: "active" | "inactive" | "prospect" | "churned"
  what_we_do?: string
  health_score: number
  health_label: "on_track" | "at_risk" | "needs_attention" | "critical"
  last_activity_at?: string
  created_at: string
}

export interface ClientDetail extends Client {
  engagements: Engagement[]
  client_notes: ClientNote[]
  invoices: { id: string; total: number; status: string; due_date: string }[]
  contracts: { id: string; type: string; status: string }[]
  proposals: { id: string; title: string; total_amount: number; status: string }[]
  retainers: { id: string; title: string; amount: number; status: string }[]
}

export interface Engagement {
  id: string
  client_id: string
  title: string
  description_md?: string
  engagement_type: "project" | "retainer" | "one_off" | "ongoing"
  status: "planning" | "active" | "on_track" | "at_risk" | "paused" | "done" | "cancelled"
  start_date?: string
  target_end_date?: string
  budget?: number
  value_delivered: number
  contract_id?: string
  created_at: string
}

export interface QuickCapture {
  id: string
  raw_text: string
  parse_status: "pending" | "parsed" | "failed" | "partial"
  parsed_intent?: string
  parsed_entities?: Record<string, unknown>
  ai_confidence?: number
  actions_taken?: Record<string, unknown>[]
  requires_review: boolean
  created_at: string
}

export interface Proposal {
  id: string
  client_id?: string
  title: string
  proposal_number?: string
  content_md?: string
  total_amount: number
  currency: string
  pricing_type: string
  payment_terms: string
  status: "draft" | "sent" | "viewed" | "accepted" | "declined" | "expired"
  valid_until?: string
  pdf_url?: string
  contract_id?: string
  created_at: string
}

export interface Retainer {
  id: string
  client_id?: string
  title: string
  amount: number
  currency: string
  billing_cycle: "weekly" | "monthly" | "quarterly" | "annual"
  start_date: string
  end_date?: string
  next_invoice_date?: string
  status: "active" | "paused" | "cancelled"
  auto_invoice: boolean
}

export interface ButlerState {
  memory: {
    last_briefing_at?: string
    last_briefing_summary?: string
    client_count: number
    active_engagement_count: number
    rolling_insights: string[]
  }
  last_briefing?: {
    title: string
    body: string
    created_at: string
  }
}
```
