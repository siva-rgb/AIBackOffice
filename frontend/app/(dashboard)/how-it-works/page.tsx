import Link from 'next/link';
import {
  Sparkles,
  BookOpen,
  FileText,
  FileSignature,
  TrendingUp,
  Bell,
  Bot,
  Link2,
  ArrowRight,
  Clock,
  Sun,
  User,
  Cpu,
  Check,
  Calendar,
  Mail,
  Video,
  BrainCircuit,
  Briefcase,
  Shield,
  Zap,
  Eye,
  RefreshCw,
  MessageSquare,
  Database,
  AlertTriangle,
  Activity,
  BookMarked,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/ui';

export const metadata = { title: 'How Kora works' };

const AUDIENCE = [
  {
    title: 'Freelancers',
    body: 'Designers, developers, writers, consultants — anyone who invoices clients and manages their own books. Kora replaces your spreadsheets and reminder calendar.',
  },
  {
    title: 'Micro-businesses',
    body: 'Teams of 1–5 who need a real back-office without a dedicated finance or ops person. Get enterprise-level business intelligence at a fraction of the cost.',
  },
  {
    title: 'Online sellers',
    body: 'Etsy, Fiverr, and marketplace sellers who want professional invoicing, clean financials, and contract protection as they grow.',
  },
  {
    title: 'Side hustlers turning pro',
    body: 'Anyone with real client income who wants it run like a proper business — forecasts, contracts, follow-ups, and books — on autopilot.',
  },
];

const FEATURES = [
  {
    icon: BrainCircuit,
    name: 'Business Manager',
    href: '/manager',
    what: 'Your AI CFO that reviews everything at once. It gathers your live financials (transactions, invoices, contracts, cash flow) and your client relationship health, assesses what needs doing, runs safe actions automatically, and queues risky ones for your approval. You get a plain-English briefing with specific numbers, your top priorities, and one-click actions.',
    details: [
      'Reconciles payments automatically — matches bank deposits to outstanding invoices without you touching a thing',
      'Re-categorizes any uncategorized transactions before showing you the books',
      'Follows an escalation ladder for overdue invoices: gentle reminder → firm follow-up → formal payment demand letter → bad-debt write-off proposal',
      'Queues every client-facing action for YOUR approval before anything is sent — nothing goes out without your say',
      'Maintains rolling memory across runs — each briefing reads the previous one and continues the story',
      'Conversation mode: ask "how am I tracking against my revenue goal?" and it queries your live data to answer with real numbers',
    ],
    helps: 'Instead of checking five tools and making the connections yourself, one click gives you a full cross-business assessment with prioritized actions.',
  },
  {
    icon: Briefcase,
    name: 'Butler — Client Intelligence',
    href: '/butler',
    what: 'An AI business partner focused entirely on your client relationships. It computes a health score (0–100) for every client from real signals: overdue invoices drag the score down, at-risk engagements reduce it further, and silence (21+ days of no activity) is flagged as a warning. Each morning it generates a personalized briefing about your clients — who needs attention, who\'s going quiet, what engagements are at risk.',
    details: [
      'Health scores are deterministic and computed server-side — no hallucination, just your actual data',
      'Health drops for overdue money (–15 to –40 depending on count), at-risk engagements (–20), and client silence (–15 after 21 days)',
      'Enriches each morning briefing with Google data when connected: today\'s client meetings, clients who need email replies, strained email relationships',
      'Quick Capture: type a rough note like "Alice mentioned budget constraints" and the Butler parses it, creates a client note, and optionally updates the engagement status — all with one free-text input',
      'Tracks every engagement with status progression: planning → active → on_track → at_risk, so you always know where each project stands',
      'Rolling memory: each Butler briefing reads the previous session\'s summary and highlights what\'s changed',
    ],
    helps: 'Your client relationships are your business. Butler keeps you from letting good relationships go cold or missing the early signals of a client about to churn.',
  },
  {
    icon: BookMarked,
    name: 'Business Playbook — Learning Memory',
    href: '/settings',
    what: 'Kora\'s memory system that gets smarter about YOUR business over time. It watches seven types of events silently in the background and builds up a personal knowledge base: your communication style, how your clients actually pay, your billing patterns, what actions you repeatedly dismiss, and facts extracted from your emails and meetings. This context is injected into every AI call — the agents always know your specific business.',
    details: [
      'Observer 1 — Decisions: records every task you approve or dismiss; after 3+ dismissals of the same type, creates a "business rule" to stop proposing it',
      'Observer 2 — Corrections: when you fix a transaction category, stores it as a permanent correction at confidence 1.0 — next time that same payee appears, the AI skips the LLM entirely and applies your override directly',
      'Observer 3 — Email edits: if you edit an email draft before approving, it extracts your length preference, tone, and greeting style',
      'Observer 4 — Payments: records how each client actually pays (early, on-time, late) after each reconciliation',
      'Observer 5 — Gmail intel: bridges relationship health, pending commitments, and financial mentions from email analysis into long-term memory',
      'Observer 6 — Meetings: stores client commitments and financial figures mentioned in meeting transcripts',
      'Observer 7 — Onboarding: seeds your business type, industry, hourly rate, brand tone, and payment terms from your profile on day one',
      'Pattern detection: finds income seasonality, billing rhythm (which day of the month you typically invoice), and per-client payment reliability from your history',
    ],
    helps: 'After a few weeks of normal use, every agent response is personalized to you. Your corrections never need to be made twice. The AI knows your clients, your preferences, and your business patterns.',
  },
  {
    icon: BookOpen,
    name: 'AI Bookkeeper',
    href: '/bookkeeping',
    what: 'Upload a bank statement (CSV) and every transaction is auto-categorized using AI — income streams split out, expenses tagged to the right category, and tax-deductible items flagged. A P&L report is generated as a downloadable PDF. You review only the handful the AI marks as low-confidence.',
    details: [
      'Applies your Playbook corrections first — if you\'ve ever corrected a payee\'s category, it\'s applied instantly without calling the AI (saving tokens and cost)',
      'Batches uncorrected transactions to the LLM with your business context pre-loaded from the Playbook',
      'Flags items where confidence < 70% for manual review so you\'re only touching genuinely ambiguous entries',
      'One-click category correction on any transaction trains the Playbook immediately for future uploads',
      'Full transaction history with search, filter by type, and month-by-month breakdown',
    ],
    helps: 'No more spreadsheets at tax time. Upload once, get a complete P&L, and only spend time on the 5–10% that genuinely needs human judgement.',
  },
  {
    icon: FileText,
    name: 'Invoice Agent',
    href: '/invoices',
    what: 'Create professional invoices and let the agent chase them for you. It watches every unpaid invoice and sends personalized follow-ups on a calibrated schedule — referencing the exact invoice number, amount, client name, and days overdue. The escalation ladder runs automatically: gentle reminder (day 3) → firm follow-up (day 7) → final notice (day 14) → formal payment demand (after 14+ days with 2+ prior reminders). Unresponsive invoices eventually reach a write-off proposal.',
    details: [
      'Every follow-up email is AI-generated and personalized — not a generic template',
      'Escalation is fully automatic but every step is queued for your approval before sending',
      'Invoices linked to contracts get follow-ups that reference the contract terms — stronger legally grounded language',
      'Cross-module: a signed contract with a payment schedule automatically creates the matching invoices',
      'When an invoice is marked paid via bank reconciliation, all pending follow-ups for it are cancelled automatically',
    ],
    helps: 'You get paid faster without having to track who owes what or write uncomfortable follow-up emails. The AI is consistent, polite, and remembers to escalate when you\'d forget.',
  },
  {
    icon: FileSignature,
    name: 'Contract Generator',
    href: '/contracts/new',
    what: 'Describe a deal in plain English and the AI drafts a complete, professional contract — NDA, freelance services agreement, consulting contract, retainer agreement, and more. Every clause is explained in plain language beside the legal text. Contracts have a full status lifecycle: draft → sent → signed, and signing triggers downstream actions.',
    details: [
      'Jurisdiction-aware drafting: the AI considers your business location and generates locally appropriate clauses',
      'Every clause includes a plain-English "what this means" explanation so you understand what you\'re sending',
      'When a contract is signed, the cross-module agent reads its payment schedule and creates the matching invoices automatically',
      'Linked contracts give invoice follow-ups stronger language — the demand letter references the exact contract terms',
      'Playbook context (your typical payment terms, standard rate, brand tone) is injected so contracts match your usual style',
    ],
    helps: 'Professional legal protection in ~20 seconds. The AI handles the tedious part; you review and send. No more sending work without a contract because writing one felt like too much effort.',
  },
  {
    icon: TrendingUp,
    name: 'Cash Flow Forecast',
    href: '/cashflow',
    what: 'A 90-day rolling projection in three scenarios — optimistic, expected, and conservative — using your real current balance, all open invoices (weighted by how overdue they are and how likely each client is to pay), and your historical monthly income patterns. The conservative projection drives the danger alert: if it predicts your balance going negative, the Business Manager raises a critical alert.',
    details: [
      'Open invoices are weighted by payment probability based on days overdue and the client\'s historical payment reliability (from the Playbook)',
      'Three scenarios let you see the range: optimistic assumes all invoices pay on schedule, conservative assumes the late ones stay late',
      'The "danger days" metric tells you exactly how many days until the conservative scenario goes negative — giving you weeks to act, not days',
      'Cash danger triggers an automatic critical alert on the dashboard and in the Business Manager briefing',
      'Forecast is refreshed every time the Business Manager runs, so it always reflects the latest paid/unpaid state',
    ],
    helps: 'You know months ahead whether you can afford to take on a new hire, survive a slow season, or whether you need to chase payments harder right now — not after a crisis has already hit.',
  },
  {
    icon: Mail,
    name: 'Gmail Email Intelligence',
    href: '/butler/email',
    what: 'Kora reads your email threads with each active client (with your permission via Google OAuth) and extracts structured business intelligence: relationship health (strong/healthy/needs_attention/at_risk), sentiment (positive/neutral/cautious/strained), pending commitments, unresolved questions, and financial mentions. Results are cached for 24 hours and only refreshed when new messages arrive.',
    details: [
      'Analyzes up to 10 recent threads per client, reading the last 5 messages per thread as snippets',
      'Detects when a client hasn\'t replied to your last message and flags it as action_needed',
      'Tracks financial mentions (invoices, payments, quotes, refunds) discussed in email threads',
      'Strained relationships and clients needing replies surface in the Butler morning briefing automatically',
      'Email intelligence feeds into the Playbook: relationship health, commitments, and financial mentions become long-term memory',
      '"Draft follow-up" generates a personalized email using the relationship context, your email style preferences (from Playbook), and specified tone — queued for approval before sending',
    ],
    helps: 'You see every client relationship\'s health in one view, with the specific emails driving those signals. No more wondering "did I reply to that?" or "are they upset about something?"',
  },
  {
    icon: Calendar,
    name: 'Calendar & Scheduling',
    href: '/butler/calendar',
    what: 'Integrates with Google Calendar to show today\'s client meetings, surface past meetings that were never logged in Kora, suggest available time slots, and queue meeting scheduling requests. Every calendar action goes through the human-approval flow — Kora proposes, you approve.',
    details: [
      'Today\'s meetings shows title, time, and a direct "Join" button for Google Meet links',
      'Client badge chips identify which of your known clients are in each meeting',
      'Unlogged meetings: past calendar events that don\'t have a Kora meeting record yet — one click logs them',
      'Schedule a meeting: fill in title, date/time, duration, and attendee emails → queued as a manager task for your approval before Kora creates the Google Calendar event',
      'Available slot chips (from Google Calendar free/busy analysis) let you click to prefill the schedule form with a suggested time',
      'Logging a past meeting from the Calendar page creates a quick-note meeting record that the Meeting Agent can later parse for action items',
    ],
    helps: 'Your calendar and your business data live together. You never miss that a client meeting happened and wasn\'t followed up on, and scheduling a meeting is one form instead of back-and-forth emails.',
  },
  {
    icon: Video,
    name: 'Meeting Intelligence',
    href: '/butler/meetings',
    what: 'Upload a meeting transcript (plain text, VTT subtitles, SRT, PDF, or DOCX) and Kora\'s Meeting Agent parses it into a complete minutes-of-meeting record: summary, decisions, client commitments, risks flagged, next steps with owners and deadlines, overall sentiment, and a confidence score. Action items are tracked with checkboxes you can tick off as you complete them.',
    details: [
      'Two-step upload: first creates the meeting record, then uploads the file so large transcripts process in the background',
      'Quick note mode: type rough notes from a meeting and the agent still extracts structure from them',
      'Action items have owner, due date, priority (high/medium/low), and status (open/done) — checkbox toggles update in real time',
      'Commitments are separated by who made them: you vs. the client — so client commitments are clearly visible for follow-up',
      'Risks flagged includes severity level — so a "critical risk" mentioned in passing is surfaced, not buried in the transcript',
      'Meeting intelligence feeds the Playbook: client commitments and financial figures mentioned become long-term memory that informs future agent behavior',
      'Meeting action items that are overdue surface in the Butler morning briefing',
    ],
    helps: 'Every meeting produces structured, searchable records. You know exactly what was agreed, who owes what by when, and what risks were raised — without anyone taking notes.',
  },
  {
    icon: Link2,
    name: 'Cross-Module Intelligence',
    href: '/contracts',
    what: 'The agents share data through a common store and trigger each other on events. Sign a contract → invoices are created from its payment schedule. A transaction matches an invoice amount → it\'s reconciled and marked paid, follow-ups are cancelled. An overdue invoice linked to a contract gets a demand letter grounded in its specific terms. This happens automatically — zero clicks.',
    details: [
      'Contract signed → cross_module agent reads the payment schedule and creates milestone invoices with correct amounts and due dates',
      'Bank transaction matches open invoice (by amount + client) → invoice marked paid, pending follow-up tasks cancelled',
      'Payment reconciliation feeds the Playbook with client payment speed data',
      'Business Manager runs reconciliation as its first step on every review, before assessing what invoices to chase',
      'All cross-module actions are logged with what triggered them, so you always have an audit trail',
    ],
    helps: 'The work that normally falls between tools — "did I create the invoice from the contract?", "did that payment come in?" — just happens. Nothing slips through the cracks between your legal, billing, and books.',
  },
  {
    icon: Bell,
    name: 'Proactive Alerts',
    href: '/dashboard',
    what: 'The dashboard surfaces critical alerts as they are generated: cash flow going negative, overdue invoice pile-ups, the morning Butler briefing, and unusual expense patterns. Alerts are deduped (the same type of critical alert won\'t fire more than once every 3 days) so you get signal, not noise.',
    details: [
      'Cash flow danger alert fires when the conservative 90-day projection turns negative — with the specific number of days until it happens',
      'Morning briefing alert fires once per day from the Butler — a one-sentence summary with a link to the full briefing',
      'Alerts have severity levels (info / warning / critical) with corresponding visual weight so the most urgent items stand out',
      'Read/unread state per alert so you can clear what you\'ve seen',
    ],
    helps: 'The most important problems reach you proactively, with specific numbers and a suggested next step — not as a surprise weeks later.',
  },
  {
    icon: Bot,
    name: 'Agent Audit Log',
    href: '/agents',
    what: 'Every action every agent takes is recorded: what it saw (input), what it did (output), which AI model it used, how many tokens it consumed, how long it took, what it cost in USD, and what triggered it. Nothing happens in a black box.',
    details: [
      'Agent types tracked: bookkeeper, invoice follow-up, contract generator, cashflow forecaster, alert generator, supervisor, butler, gmail, calendar, drive, meeting agent, chat, and playbook',
      'Input/output logged for every call so you can see exactly what data the agent was reasoning over',
      'Cost per call tracked in USD — you can see the total cost of running your AI back-office',
      'Triggered-by field: user, scheduler, or cross_module — so you know what initiated each action',
      'Full log is exportable for your records',
    ],
    helps: 'Full transparency and accountability. You can always verify exactly what the AI did on your behalf and why — and use the log to understand how decisions were made.',
  },
];

const HITL_TASKS = [
  { kind: 'send_followup', label: 'Invoice follow-up email', why: 'Goes to a real client on your behalf' },
  { kind: 'send_demand', label: 'Formal payment demand letter', why: 'Legal escalation, irreversible' },
  { kind: 'writeoff_invoice', label: 'Write off bad debt', why: 'Permanent financial record change' },
  { kind: 'create_calendar_event', label: 'Create Google Calendar event', why: 'Sends invites to clients' },
  { kind: 'send_email_gmail', label: 'Send email via Gmail', why: 'External communication in your name' },
  { kind: 'send_meeting_followup', label: 'Meeting follow-up email', why: 'Post-meeting commitments, goes to clients' },
];

const TIMELINE = [
  {
    icon: Sun,
    time: 'Morning',
    name: 'Butler morning briefing',
    body: 'Refreshes every client\'s health score, reads today\'s calendar, checks email intel for clients needing replies, and generates a personalized briefing: who needs attention, what\'s at risk, what\'s going well.',
  },
  {
    icon: BrainCircuit,
    time: 'On demand',
    name: 'Business Manager review',
    body: 'Reconciles payments, recategorizes uncategorized transactions, refreshes the 90-day forecast, assesses all overdue invoices, queues new approvals, and writes a briefing with your top priorities and specific numbers.',
  },
  {
    icon: Mail,
    time: 'Daily (background)',
    name: 'Gmail email intel sync',
    body: 'For each active client with an email address, scans the last 10 threads. Only runs if new messages arrived since the last sync. Updates relationship health, sentiment, pending commitments, and action flags.',
  },
  {
    icon: FileText,
    time: 'Event-triggered',
    name: 'Invoice follow-up agent',
    body: 'Fires when an invoice crosses a follow-up threshold. Generates a personalized email, queues it for your approval. Escalates from gentle reminder to firm note to formal demand letter as time passes.',
  },
  {
    icon: Link2,
    time: 'Instant',
    name: 'Cross-module triggers',
    body: 'A signed contract creates invoices. A matched bank deposit marks the invoice paid and cancels pending reminders. Categorized expenses update the forecast. Immediate — no cron job, no delay.',
  },
  {
    icon: BookMarked,
    time: 'Passive, always',
    name: 'Playbook observations',
    body: 'Every approve, dismiss, category correction, email edit, payment, email analysis, and meeting you process silently adds to your Playbook. The agents get more personalized with every action you take.',
  },
];

export default function AboutPage() {
  return (
    <div className="space-y-16">
      {/* Hero */}
      <section className="rounded-2xl bg-gradient-to-br from-kora-600 to-kora-700 px-8 py-12 text-white">
        <div className="flex items-center gap-2 text-kora-100">
          <Sparkles size={18} />
          <span className="text-xs font-semibold uppercase tracking-wide">How Kora works</span>
        </div>
        <h1 className="mt-3 max-w-2xl text-3xl font-extrabold leading-tight">
          An AI team running your back-office — with you in control.
        </h1>
        <p className="mt-3 max-w-2xl text-base leading-relaxed text-kora-50">
          Kora is a coordinated system of AI agents — not a dashboard you manually operate. Each agent
          specializes in one domain (books, invoices, contracts, client relationships, email, meetings)
          but they share data, trigger each other, and learn from every action you take. The result is
          a business that runs itself on the routine stuff, while keeping you in control of every
          decision that matters.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/manager"
            className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-kora-700 hover:bg-kora-50"
          >
            Open Business Manager <ArrowRight size={15} />
          </Link>
          <Link
            href="/butler"
            className="inline-flex items-center gap-2 rounded-lg border border-white/40 px-4 py-2 text-sm font-semibold text-white hover:bg-white/10"
          >
            Open Butler
          </Link>
        </div>
      </section>

      {/* Who it's for */}
      <section>
        <h2 className="text-lg font-bold text-gray-900">Who Kora is built for</h2>
        <p className="mt-1 text-sm text-gray-500">
          The 59 million people running a real business who were handed tools built for someone else.
        </p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {AUDIENCE.map((a) => (
            <Card key={a.title} className="p-5">
              <p className="text-sm font-semibold text-gray-900">{a.title}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-gray-500">{a.body}</p>
            </Card>
          ))}
        </div>
      </section>

      {/* The HITL safety principle */}
      <section className="rounded-2xl border border-amber-200 bg-amber-50 px-6 py-6">
        <div className="flex items-start gap-3">
          <Shield size={20} className="mt-0.5 shrink-0 text-amber-600" />
          <div>
            <h2 className="text-base font-bold text-amber-900">The human-in-the-loop guarantee</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-amber-800">
              Kora will never send a client email, create a calendar event, write off an invoice, or take
              any irreversible action without your explicit approval. Every agent that wants to act
              externally creates a <strong>proposed task</strong> in your Manager page. You review it,
              see exactly what it will do and why, and click Approve or Dismiss. Only after you approve
              does Kora act. This is not a setting — it is how the system is architecturally wired.
            </p>
            <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {HITL_TASKS.map((t) => (
                <div key={t.kind} className="flex items-start gap-2 rounded-lg bg-white px-3 py-2.5 text-xs">
                  <Shield size={12} className="mt-0.5 shrink-0 text-amber-500" />
                  <div>
                    <p className="font-semibold text-gray-900">{t.label}</p>
                    <p className="text-gray-500">{t.why}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Features — full detail */}
      <section>
        <h2 className="text-lg font-bold text-gray-900">Every capability, in detail</h2>
        <p className="mt-1 text-sm text-gray-500">What each part does, how it actually works under the hood, and how it helps you.</p>
        <div className="mt-5 space-y-4">
          {FEATURES.map((f) => (
            <Card key={f.name} className="p-6">
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-kora-50 text-kora-600">
                  <f.icon size={20} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-base font-bold text-gray-900">{f.name}</h3>
                    <Link href={f.href} className="shrink-0 text-xs font-medium text-kora-600 hover:underline">
                      Open →
                    </Link>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-gray-700">{f.what}</p>

                  <div className="mt-3 space-y-1.5">
                    {f.details.map((d, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs leading-relaxed text-gray-600">
                        <Zap size={12} className="mt-0.5 shrink-0 text-kora-400" />
                        <span>{d}</span>
                      </div>
                    ))}
                  </div>

                  <div className="mt-3 flex items-start gap-2 rounded-lg bg-emerald-50 px-3 py-2.5 text-xs leading-relaxed text-emerald-800">
                    <Check size={13} className="mt-0.5 shrink-0" />
                    <span>{f.helps}</span>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* How agents communicate */}
      <section>
        <h2 className="text-lg font-bold text-gray-900">How the agents talk to each other</h2>
        <p className="mt-1 text-sm text-gray-500">
          The agents don&apos;t call each other directly. They share a common data store — and that&apos;s intentional.
        </p>
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <Card className="p-5">
            <div className="flex items-center gap-2 text-kora-600 mb-3">
              <BrainCircuit size={16} />
              <p className="text-sm font-bold text-gray-900">Business Manager (Supervisor)</p>
            </div>
            <p className="text-xs leading-relaxed text-gray-600">
              The Manager orchestrates three subordinate agents — Bookkeeper, Cashflow Forecaster, and Cross-Module.
              It gathers state from all of them, assesses the full picture, takes safe actions (reconcile, categorize),
              then queues everything else for approval. It runs on your schedule and remembers its last briefing.
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {['Bookkeeper', 'Cashflow', 'Cross-Module', 'Invoice Follow-up'].map((a) => (
                <span key={a} className="rounded-full bg-kora-50 px-2 py-0.5 text-[10px] font-medium text-kora-700">{a}</span>
              ))}
            </div>
          </Card>
          <Card className="p-5">
            <div className="flex items-center gap-2 text-kora-600 mb-3">
              <Briefcase size={16} />
              <p className="text-sm font-bold text-gray-900">Butler (Independent)</p>
            </div>
            <p className="text-xs leading-relaxed text-gray-600">
              The Butler runs independently and focuses entirely on client relationships. It reads the same data
              store (clients, invoices, engagements, meetings, email intel) but produces a different perspective —
              a client-centric briefing. It doesn&apos;t report to the Manager; they share data, not a chain of command.
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {['Gmail Intel', 'Calendar Intel', 'Meeting Agent', 'Quick Capture'].map((a) => (
                <span key={a} className="rounded-full bg-kora-50 px-2 py-0.5 text-[10px] font-medium text-kora-700">{a}</span>
              ))}
            </div>
          </Card>
          <Card className="p-5 lg:col-span-2">
            <div className="flex items-center gap-2 text-kora-600 mb-3">
              <BookMarked size={16} />
              <p className="text-sm font-bold text-gray-900">Business Playbook (Memory layer, always active)</p>
            </div>
            <p className="text-xs leading-relaxed text-gray-600">
              The Playbook is not an agent but a shared memory layer all agents read from. Every agent call injects
              a &ldquo;Business Context&rdquo; block from the Playbook — your preferences, corrections, business rules, and
              client facts. On day one this block is empty. After a month of use it contains dozens of personalized
              facts that make every AI response more accurate and relevant to your specific business.
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {['Decisions', 'Corrections', 'Email edits', 'Payment speed', 'Email intel', 'Meeting data', 'Onboarding'].map((a) => (
                <span key={a} className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">{a}</span>
              ))}
            </div>
          </Card>
        </div>
      </section>

      {/* Activity timeline */}
      <section>
        <h2 className="text-lg font-bold text-gray-900">What happens, when, and why</h2>
        <p className="mt-1 text-sm text-gray-500">
          A typical day in Kora — most of it requires zero input from you.
        </p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {TIMELINE.map((d) => (
            <Card key={d.name} className="p-5">
              <div className="flex items-center gap-2 text-kora-600">
                <d.icon size={15} />
                <span className="text-xs font-bold uppercase tracking-wide text-kora-600">{d.time}</span>
              </div>
              <p className="mt-2 text-sm font-semibold text-gray-900">{d.name}</p>
              <p className="mt-1 text-xs leading-relaxed text-gray-500">{d.body}</p>
            </Card>
          ))}
        </div>
        <p className="mt-3 text-xs text-gray-400">
          Every one of these actions is timestamped and logged in your{' '}
          <Link href="/agents" className="text-kora-600 hover:underline">Agent Audit Log</Link>{' '}
          — with the model used, tokens consumed, cost in USD, and full input/output.
        </p>
      </section>

      {/* You vs AI */}
      <section className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="What you control" subtitle="The strategic and irreversible decisions stay with you" />
          <ul className="space-y-2.5 px-5 pb-5 text-sm text-gray-700">
            {[
              'Which clients to take and how to price your work',
              'Whether to approve or dismiss any proposed agent action before it runs',
              'Reviewing and editing email drafts before they are sent',
              'Decisions on overdue invoices — escalate, extend, or write off',
              'The handful of low-confidence transactions the AI flags for review',
              'When to run a full Business Manager review',
            ].map((t) => (
              <li key={t} className="flex items-start gap-2">
                <User size={14} className="mt-0.5 shrink-0 text-gray-400" />
                {t}
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title="What the agents handle" subtitle="The repetitive, time-consuming execution" />
          <ul className="space-y-2.5 px-5 pb-5 text-sm text-gray-700">
            {[
              'Categorizing every transaction and building the P&L',
              'Drafting follow-up emails for overdue invoices on the right schedule',
              'Reconciling bank deposits against open invoices',
              'Generating contracts and explaining every clause',
              'Forecasting cash flow and raising alerts before you\'d notice',
              'Analysing email threads and surfacing relationship health and action flags',
              'Parsing meeting transcripts into decisions, commitments, action items, and risks',
              'Learning your preferences and applying them to every future action',
            ].map((t) => (
              <li key={t} className="flex items-start gap-2">
                <Cpu size={14} className="mt-0.5 shrink-0 text-kora-500" />
                {t}
              </li>
            ))}
          </ul>
        </Card>
      </section>

      {/* How it gets smarter */}
      <section>
        <h2 className="text-lg font-bold text-gray-900">How Kora gets smarter about your business over time</h2>
        <p className="mt-1 text-sm text-gray-500">
          The Playbook turns usage into personalization. Here&apos;s the progression:
        </p>
        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          {[
            {
              label: 'Week 1',
              title: 'Baseline',
              items: [
                'Business type, industry, and goals from your profile',
                'Default payment terms and hourly rate',
                'Communication brand tone preference',
              ],
              color: 'bg-gray-50',
            },
            {
              label: 'Month 1',
              title: 'Learning your patterns',
              items: [
                'Which transaction descriptions map to which categories (from your corrections)',
                'How each client actually pays — early, on time, or late',
                'Which agent actions you approve vs. repeatedly dismiss',
                'Your email writing style from any drafts you\'ve edited',
              ],
              color: 'bg-kora-50',
            },
            {
              label: 'Month 3+',
              title: 'Deeply personalized',
              items: [
                'Income seasonality patterns and typical billing day',
                'Per-client relationship intelligence from email history',
                'Business rules inferred from your behaviour ("never propose X for client Y")',
                'Commitments and financial figures from meeting transcripts',
                'Corrections bypass the LLM entirely — instant, zero-cost categorization for known payees',
              ],
              color: 'bg-emerald-50',
            },
          ].map((stage) => (
            <div key={stage.label} className={`rounded-xl ${stage.color} p-5`}>
              <span className="text-xs font-bold uppercase tracking-wide text-gray-500">{stage.label}</span>
              <p className="mt-1 text-sm font-semibold text-gray-900">{stage.title}</p>
              <ul className="mt-3 space-y-1.5">
                {stage.items.map((item) => (
                  <li key={item} className="flex items-start gap-2 text-xs leading-relaxed text-gray-600">
                    <Check size={12} className="mt-0.5 shrink-0 text-kora-500" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* Value stats */}
      <section>
        <h2 className="text-lg font-bold text-gray-900">What this is worth in practice</h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          {[
            {
              stat: '4–6 hrs',
              label: 'saved every month',
              sub: 'Admin time returned to billable work — roughly $300–$450 at a $75/hr rate. Bookkeeping, follow-ups, and contract drafting are the biggest contributors.',
            },
            {
              stat: '18–23%',
              label: 'more overdue payments recovered',
              sub: 'Consistent, timely, escalating follow-ups collect what manual chasing leaves on the table — especially for 7–21 day overdue invoices.',
            },
            {
              stat: '~10 min',
              label: 'of admin per week',
              sub: 'Upload a CSV, approve or dismiss a handful of agent proposals, glance at the forecast. The rest — categorization, chasing, emails, reconciliation — runs itself.',
            },
          ].map((v) => (
            <Card key={v.label} className="p-6">
              <p className="text-3xl font-extrabold text-kora-600">{v.stat}</p>
              <p className="mt-1 text-sm font-semibold text-gray-900">{v.label}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-gray-500">{v.sub}</p>
            </Card>
          ))}
        </div>
      </section>

      {/* Getting started */}
      <section>
        <h2 className="text-lg font-bold text-gray-900">Where to start</h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { step: '1', title: 'Complete your profile', body: 'Business type, industry, payment terms, and goals seed the Playbook immediately.', href: '/settings', cta: 'Open settings' },
            { step: '2', title: 'Upload a bank statement', body: 'Drop in any CSV from your bank. The Bookkeeper categorizes everything and builds your first P&L.', href: '/bookkeeping', cta: 'Go to Bookkeeping' },
            { step: '3', title: 'Connect Google', body: 'Link your Google account to activate Gmail email intel, Calendar, and the Butler\'s full morning briefing.', href: '/settings', cta: 'Connect Google' },
            { step: '4', title: 'Run a Manager review', body: 'Open the Business Manager and run your first review. It will find anything that needs attention and queue actions.', href: '/manager', cta: 'Open Manager' },
          ].map((s) => (
            <Card key={s.step} className="p-5">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-kora-600 text-sm font-bold text-white">
                {s.step}
              </div>
              <p className="mt-3 text-sm font-semibold text-gray-900">{s.title}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-gray-500">{s.body}</p>
              <Link href={s.href} className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-kora-600 hover:underline">
                {s.cta} <ArrowRight size={12} />
              </Link>
            </Card>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="rounded-2xl border border-gray-200 bg-white px-8 py-10 text-center">
        <h2 className="text-xl font-bold text-gray-900">Ready to let the agents take over the admin?</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-gray-500">
          The agents handle the execution. You stay in control of every decision that matters.
          Start in under 5 minutes.
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-3">
          <Link
            href="/manager"
            className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-kora-700"
          >
            Open Business Manager <ArrowRight size={15} />
          </Link>
          <Link
            href="/butler"
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-5 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            Open Butler
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-5 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            Back to dashboard
          </Link>
        </div>
      </section>
    </div>
  );
}
