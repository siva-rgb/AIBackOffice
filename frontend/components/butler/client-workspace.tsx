'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  ArrowLeft, Plus, Loader2, RefreshCw, FileText, FileSignature, Repeat,
  AlertTriangle, CheckCircle2, Briefcase, NotebookPen, Pencil, X, Video, Square,
  Mail, Calendar, HardDrive, ListTodo, Ban,
} from 'lucide-react';
import { Card, CardHeader, Badge, StatCard } from '@/components/ui';
import { FormattedText } from '@/components/formatted-text';
import { authedFetch } from '@/lib/api/browser';
import { formatMoney, formatDate, humanize, cn } from '@/lib/utils';
import type {
  ClientDetail, Engagement, ClientNote, Meeting,
  EmailIntel, CalendarEvent, UnloggedMeeting, DriveDoc,
  ClientTask, TaskStatus,
} from '@/lib/api/types';

const TABS = ['overview', 'tasks', 'engagements', 'notes', 'meetings', 'email', 'calendar', 'drive', 'financials'] as const;
type Tab = (typeof TABS)[number];

const input =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';

function healthTone(score: number) {
  return score >= 75 ? 'text-emerald-600' : score >= 50 ? 'text-amber-600' : 'text-red-600';
}

export function ClientWorkspace({ detail }: { detail: ClientDetail }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialTab = searchParams.get('tab');
  const [tab, setTab] = useState<Tab>(
    (TABS as readonly string[]).includes(initialTab ?? '') ? (initialTab as Tab) : 'overview',
  );
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const cur = detail.currency || 'USD';

  async function refreshHealth() {
    setBusy(true);
    try {
      await authedFetch(`/api/clients/${detail.id}/health`, { method: 'POST' });
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Link href="/butler" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft size={15} /> Back to Butler
      </Link>

      {/* Header */}
      {editing ? (
        <EditClientForm
          detail={detail}
          onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); router.refresh(); }}
        />
      ) : (
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-gray-900">{detail.name}</h1>
              <Badge value={detail.status} />
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium capitalize text-gray-600">
                {detail.clientType}
              </span>
            </div>
            {detail.whatWeDo && <p className="mt-1 text-sm text-gray-600">{detail.whatWeDo}</p>}
            <p className="mt-1 text-xs text-gray-400">
              {[detail.company, detail.industry, detail.email].filter(Boolean).join(' · ')}
            </p>
            {detail.contactEmails && detail.contactEmails.length > 0 && (
              <p className="mt-0.5 text-xs text-gray-400">
                +{detail.contactEmails.length} contact{detail.contactEmails.length > 1 ? 's' : ''}: {detail.contactEmails.join(', ')}
              </p>
            )}
          </div>
          <div className="text-right">
            <button onClick={() => setEditing(true)}
              className="mb-2 inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:border-kora-300 hover:text-kora-700">
              <Pencil size={12} /> Edit
            </button>
            <p className={cn('text-3xl font-bold tabular-nums', healthTone(detail.healthScore))}>
              {detail.healthScore}
            </p>
            <p className="text-xs text-gray-500">{humanize(detail.healthLabel)}</p>
            <button onClick={refreshHealth} disabled={busy}
              className="mt-1 inline-flex items-center gap-1 text-xs text-kora-600 hover:underline disabled:opacity-50">
              {busy ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} Recompute
            </button>
          </div>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <StatCard label="Invoiced" value={formatMoney(detail.financials.invoiced, cur)} />
          <StatCard label="Collected" value={formatMoney(detail.financials.paid, cur)} tone="green" />
          <StatCard label="Outstanding" value={formatMoney(detail.financials.outstanding, cur)}
            hint={detail.financials.overdueCount > 0 ? `${detail.financials.overdueCount} overdue` : undefined}
            tone={detail.financials.outstanding > 0 ? 'amber' : 'default'} />
        </div>
      </Card>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={cn('px-4 py-2 text-sm font-medium capitalize', tab === t
              ? 'border-b-2 border-kora-600 text-kora-700' : 'text-gray-500 hover:text-gray-900')}>
            {t}
          </button>
        ))}
      </div>

      {tab === 'overview' && <Overview detail={detail} />}
      {tab === 'tasks' && <TasksTab clientId={detail.id} initial={detail.tasks ?? []} />}
      {tab === 'engagements' && <Engagements detail={detail} />}
      {tab === 'notes' && <Notes detail={detail} />}
      {tab === 'meetings' && <MeetingsTab clientId={detail.id} />}
      {tab === 'email' && <EmailTab clientId={detail.id} />}
      {tab === 'calendar' && <CalendarTab clientId={detail.id} clientName={detail.name} />}
      {tab === 'drive' && <DriveTab clientId={detail.id} />}
      {tab === 'financials' && <Financials detail={detail} cur={cur} />}
    </div>
  );
}

const STATUSES = ['active', 'prospect', 'inactive', 'churned'] as const;
const CLIENT_TYPES = ['individual', 'company', 'agency', 'marketplace'] as const;
const INDUSTRIES = ['Design', 'Development', 'Writing', 'Marketing', 'Consulting', 'E-commerce', 'Other'];

function EditClientForm({
  detail,
  onClose,
  onSaved,
}: {
  detail: ClientDetail;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(detail.name);
  const [email, setEmail] = useState(detail.email ?? '');
  const [contactEmailsRaw, setContactEmailsRaw] = useState((detail.contactEmails ?? []).join(', '));
  const [company, setCompany] = useState(detail.company ?? '');
  const [industry, setIndustry] = useState(detail.industry ?? '');
  const [whatWeDo, setWhatWeDo] = useState(detail.whatWeDo ?? '');
  const [status, setStatus] = useState<string>(detail.status);
  const [clientType, setClientType] = useState<string>(detail.clientType);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!name.trim()) { setError('Name is required'); return; }
    setBusy(true);
    setError(null);
    const contactEmails = contactEmailsRaw
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => e.includes('@'));
    try {
      const res = await authedFetch(`/api/clients/${detail.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim() || undefined,
          contactEmails, // empty array clears them
          company: company.trim(),
          industry: industry || undefined,
          whatWeDo: whatWeDo.trim(),
          status,
          clientType,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof json.detail === 'string' ? json.detail : 'Could not save changes');
        setBusy(false);
        return;
      }
      onSaved();
    } catch (e: any) {
      setError(e?.message ?? 'Could not save changes');
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">Edit client</h2>
        <button onClick={onClose} aria-label="Cancel" className="rounded-md p-1 text-gray-400 hover:text-gray-600">
          <X size={18} />
        </button>
      </div>
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Name <span className="text-red-400">*</span></label>
            <input className={input} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Company</label>
            <input className={input} value={company} onChange={(e) => setCompany(e.target.value)} />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Primary email</label>
          <input type="email" className={input} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ap@acme.com" />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Additional contacts <span className="font-normal text-gray-400">(comma-separated)</span></label>
          <input className={input} value={contactEmailsRaw} onChange={(e) => setContactEmailsRaw(e.target.value)} placeholder="cfo@acme.com, pm@acme.com" />
          <p className="mt-1 text-xs text-gray-400">Kora also tracks email from anyone at the client’s work domain automatically.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Status</label>
            <select className={input} value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => <option key={s} value={s} className="capitalize">{s}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Type</label>
            <select className={input} value={clientType} onChange={(e) => setClientType(e.target.value)}>
              {CLIENT_TYPES.map((t) => <option key={t} value={t} className="capitalize">{t}</option>)}
            </select>
          </div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Industry</label>
          <select className={input} value={industry} onChange={(e) => setIndustry(e.target.value)}>
            <option value="">Select…</option>
            {INDUSTRIES.map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">What do you do for them?</label>
          <input className={input} value={whatWeDo} onChange={(e) => setWhatWeDo(e.target.value)} placeholder="We build and maintain their Shopify store" />
        </div>
        {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={save} disabled={busy || !name.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-5 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60">
            {busy ? <Loader2 size={15} className="animate-spin" /> : null} Save changes
          </button>
        </div>
      </div>
    </Card>
  );
}

const TASK_TONE: Record<TaskStatus, string> = {
  todo: 'bg-gray-100 text-gray-600',
  in_progress: 'bg-blue-100 text-blue-700',
  blocked: 'bg-red-100 text-red-700',
  done: 'bg-emerald-100 text-emerald-700',
  cancelled: 'bg-gray-100 text-gray-400',
};

const SOURCE_LABEL: Record<string, string> = {
  meeting: 'from meeting', email: 'from email', contract: 'from contract',
  agent: 'added by Kora', notion: 'from Notion', manual: '',
};

function TasksTab({ clientId, initial }: { clientId: string; initial: ClientTask[] }) {
  const [tasks, setTasks] = useState<ClientTask[]>(initial);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    try {
      const res = await authedFetch(`/api/tasks?client_id=${clientId}`);
      if (res.ok) setTasks(await res.json());
    } catch {
      /* keep what we have */
    }
  }

  async function addTask(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), clientId }),
      });
      if (!res.ok) throw new Error();
      setTitle('');
      await reload();
    } catch {
      setErr('Could not add the task. If this is a fresh setup, apply the tasks migration first.');
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(id: string, status: TaskStatus) {
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, status } : t)));  // optimistic
    try {
      await authedFetch(`/api/tasks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      await reload();
    } catch {
      await reload(); // revert to server truth
    }
  }

  const open = tasks.filter((t) => ['todo', 'in_progress', 'blocked'].includes(t.status));
  const done = tasks.filter((t) => ['done', 'cancelled'].includes(t.status));

  return (
    <div className="space-y-4">
      <form onSubmit={addTask} className="flex gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Add a task for this client…"
          className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500"
        />
        <button
          type="submit"
          disabled={busy || !title.trim()}
          className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />} Add
        </button>
      </form>

      {err && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{err}</div>}

      {tasks.length === 0 ? (
        <Card className="p-8 text-center">
          <ListTodo className="mx-auto text-gray-300" size={26} />
          <p className="mt-3 text-sm font-medium text-gray-500">No tasks yet</p>
          <p className="mt-1 text-xs text-gray-400">
            Add one above — or let Kora capture them automatically from meeting action items, email
            commitments and signed contracts.
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {open.map((t) => (
            <TaskRow key={t.id} task={t} onStatus={setStatus} />
          ))}
          {done.length > 0 && (
            <>
              <p className="pt-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                Completed ({done.length})
              </p>
              {done.map((t) => (
                <TaskRow key={t.id} task={t} onStatus={setStatus} />
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function TaskRow({ task, onStatus }: { task: ClientTask; onStatus: (id: string, s: TaskStatus) => void }) {
  const isDone = task.status === 'done' || task.status === 'cancelled';
  return (
    <Card className="p-3.5">
      <div className="flex items-start gap-3">
        <button
          onClick={() => onStatus(task.id, isDone ? 'todo' : 'done')}
          title={isDone ? 'Reopen' : 'Mark done'}
          className="mt-0.5 shrink-0"
        >
          {isDone
            ? <CheckCircle2 size={16} className="text-emerald-500" />
            : <Square size={16} className="text-gray-300 hover:text-kora-500" />}
        </button>
        <div className="min-w-0 flex-1">
          <p className={cn('text-sm text-gray-800', isDone && 'text-gray-400 line-through')}>{task.title}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px]">
            <span className={cn('rounded px-1.5 py-0.5 font-medium', TASK_TONE[task.status])}>
              {humanize(task.status)}
            </span>
            {task.overdue && (
              <span className="inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 font-semibold text-red-700">
                <AlertTriangle size={10} /> Overdue
              </span>
            )}
            {task.dueDate && <span className="text-gray-400">due {formatDate(task.dueDate)}</span>}
            {task.owner && task.owner !== 'me' && <span className="text-gray-400">· {task.owner}</span>}
            {SOURCE_LABEL[task.source] && <span className="text-gray-400">· {SOURCE_LABEL[task.source]}</span>}
          </div>
        </div>
        {!isDone && (
          <button
            onClick={() => onStatus(task.id, task.status === 'blocked' ? 'todo' : 'blocked')}
            title={task.status === 'blocked' ? 'Unblock' : 'Mark blocked'}
            className="shrink-0 text-gray-300 hover:text-red-500"
          >
            <Ban size={14} />
          </button>
        )}
      </div>
    </Card>
  );
}

function MeetingsTab({ clientId }: { clientId: string }) {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);

  useEffect(() => {
    authedFetch(`/api/meetings?client_id=${clientId}`)
      .then((r) => r.json())
      .then((data) => setMeetings(Array.isArray(data) ? data : []))
      .catch(() => setMeetings([]));
  }, [clientId]);

  if (meetings === null) return <Card className="p-5 text-sm text-gray-400">Loading meetings…</Card>;
  if (meetings.length === 0) {
    return (
      <Card className="p-8 text-center">
        <Video className="mx-auto text-gray-300" size={26} />
        <p className="mt-3 text-sm font-medium text-gray-500">No meetings yet</p>
        <p className="mt-1 text-xs text-gray-400">
          Upload a transcript or add a quick note on the Meetings page — it links here by client name.
        </p>
      </Card>
    );
  }
  return (
    <div className="space-y-3">
      {meetings.map((m) => (
        <Card key={m.id} className="p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-gray-900">{m.title}</p>
            <span className="shrink-0 text-xs text-gray-400">{formatDate(m.meetingDate)}</span>
          </div>
          {m.summary && <FormattedText text={m.summary} className="mt-1.5 text-xs text-gray-600" />}
          {m.meetingActionItems?.length > 0 && (
            <div className="mt-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">Action items</p>
              <ul className="mt-1 space-y-1">
                {m.meetingActionItems.map((ai) => (
                  <li key={ai.id} className="flex items-start gap-2 text-xs text-gray-700">
                    {ai.status === 'done'
                      ? <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-emerald-500" />
                      : <Square size={13} className="mt-0.5 shrink-0 text-gray-300" />}
                    <span className={cn(ai.status === 'done' && 'text-gray-400 line-through')}>{ai.description}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

const HEALTH_TONE: Record<string, string> = {
  strong: 'bg-emerald-100 text-emerald-700', healthy: 'bg-emerald-100 text-emerald-700',
  needs_attention: 'bg-amber-100 text-amber-700', at_risk: 'bg-red-100 text-red-700',
  strained: 'bg-red-100 text-red-700',
};

function EmailTab({ clientId }: { clientId: string }) {
  const [intel, setIntel] = useState<EmailIntel[] | null>(null);

  useEffect(() => {
    authedFetch(`/api/gmail/intel?client_id=${clientId}`)
      .then((r) => r.json())
      .then((data) => setIntel(Array.isArray(data) ? data : []))
      .catch(() => setIntel([]));
  }, [clientId]);

  return (
    <div className="space-y-4">
      <ButlerCompose clientId={clientId} />

      {intel === null ? (
        <Card className="p-5 text-sm text-gray-400">Loading email intel…</Card>
      ) : intel.length === 0 ? (
        <Card className="p-8 text-center">
          <Mail className="mx-auto text-gray-300" size={26} />
          <p className="mt-3 text-sm font-medium text-gray-500">No email intel yet</p>
          <p className="mt-1 text-xs text-gray-400">
            Sync Gmail from the <Link href="/butler/email" className="font-medium text-kora-600 hover:underline">Email</Link> tab.
            Kora reads your threads with this client and summarizes the relationship here.
          </p>
        </Card>
      ) : (
        intel.map((it) => (
          <Card key={it.clientId} className="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize', HEALTH_TONE[it.relationshipHealth] ?? 'bg-gray-100 text-gray-600')}>
                {humanize(it.relationshipHealth)}
              </span>
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium capitalize text-gray-600">{it.sentiment}</span>
              <span className="text-xs text-gray-400">Last contact {it.lastContactDays}d ago ({it.lastContactDirection})</span>
            </div>
            {it.summary && <FormattedText text={it.summary} className="mt-2 text-xs text-gray-600" />}
            {it.actionNeeded && it.actionDescription && (
              <div className="mt-2 flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {it.actionDescription}
              </div>
            )}
            {it.commitmentsPending?.length > 0 && (
              <p className="mt-2 text-[11px] text-gray-500">{it.commitmentsPending.length} pending commitment(s) · {it.openQuestions?.length ?? 0} open question(s)</p>
            )}
          </Card>
        ))
      )}
    </div>
  );
}

const TONES = ['professional', 'friendly', 'firm', 'concise'] as const;

// Butler drafts a client email (brand voice + relationship history), the owner
// reviews/edits, then queues it for approval — nothing sends without approval.
function ButlerCompose({ clientId }: { clientId: string }) {
  const [open, setOpen] = useState(false);
  const [intent, setIntent] = useState('');
  const [tone, setTone] = useState<string>('professional');
  const [draft, setDraft] = useState<{ subject: string; bodyText: string } | null>(null);
  const [phase, setPhase] = useState<'idle' | 'drafting' | 'queuing'>('idle');
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null);

  async function draftIt() {
    setPhase('drafting'); setResult(null); setDraft(null);
    try {
      const res = await authedFetch(`/api/clients/${clientId}/compose`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent, tone }),
      });
      if (!res.ok) throw new Error();
      const d = await res.json();
      setDraft({ subject: d.subject ?? '', bodyText: d.body_text ?? d.bodyText ?? '' });
    } catch {
      setResult({ text: 'Could not draft. Try again in a moment.', ok: false });
    } finally {
      setPhase('idle');
    }
  }

  async function queueIt() {
    if (!draft) return;
    setPhase('queuing'); setResult(null);
    try {
      const res = await authedFetch(`/api/clients/${clientId}/queue-email`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject: draft.subject, bodyText: draft.bodyText }),
      });
      const j = await res.json().catch(() => ({}));
      setResult({ text: j.note ?? (j.queued ? 'Queued for your approval.' : 'Not queued.'), ok: !!j.queued });
      if (j.queued) { setDraft(null); setIntent(''); setOpen(false); }
    } catch {
      setResult({ text: 'Could not queue the draft.', ok: false });
    } finally {
      setPhase('idle');
    }
  }

  if (!open) {
    return (
      <Card className="flex items-center justify-between gap-3 p-4">
        <div>
          <p className="text-sm font-semibold text-gray-900">Let the Butler write it</p>
          <p className="text-xs text-gray-500">Draft an email to this client in your brand voice — you approve before it sends.</p>
        </div>
        <button onClick={() => setOpen(true)}
          className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700">
          <Mail size={15} /> Ask Butler to draft…
        </button>
      </Card>
    );
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-gray-900">Ask Butler to draft an email</p>
        <button onClick={() => { setOpen(false); setDraft(null); setResult(null); }} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
      </div>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-gray-600">What should it say?</span>
        <textarea className={input} rows={2} value={intent} onChange={(e) => setIntent(e.target.value)}
          placeholder="e.g. Nudge them on the overdue invoice and offer a quick call this week." />
      </label>
      <div className="flex items-center gap-3">
        <label className="text-xs font-medium text-gray-600">Tone</label>
        <select className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm" value={tone} onChange={(e) => setTone(e.target.value)}>
          {TONES.map((t) => <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>)}
        </select>
        <button onClick={draftIt} disabled={phase === 'drafting' || intent.trim().length < 3}
          className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60">
          {phase === 'drafting' ? <Loader2 size={14} className="animate-spin" /> : <Mail size={14} />} Draft
        </button>
      </div>

      {draft && (
        <div className="space-y-2 rounded-lg border border-gray-200 bg-gray-50/60 p-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">Subject</span>
            <input className={input} value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">Body</span>
            <textarea className={input} rows={8} value={draft.bodyText} onChange={(e) => setDraft({ ...draft, bodyText: e.target.value })} />
          </label>
          <button onClick={queueIt} disabled={phase === 'queuing'}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-60">
            {phase === 'queuing' ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} Approve &amp; queue for sending
          </button>
          <p className="text-[11px] text-gray-400">You&apos;ll give final approval in the Business Manager before it sends.</p>
        </div>
      )}

      {result && (
        <div className={`rounded-lg px-3 py-2 text-xs ${result.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>
          {result.text}
        </div>
      )}
    </Card>
  );
}

function CalendarTab({ clientId, clientName }: { clientId: string; clientName: string }) {
  const [data, setData] = useState<{ today: CalendarEvent[]; unlogged: UnloggedMeeting[] } | null>(null);

  useEffect(() => {
    Promise.all([
      authedFetch('/api/calendar/today').then((r) => r.json()).catch(() => []),
      authedFetch('/api/calendar/unlogged').then((r) => r.json()).catch(() => []),
    ]).then(([today, unlogged]) => {
      const name = clientName.toLowerCase();
      setData({
        today: (Array.isArray(today) ? today : []).filter((e: CalendarEvent) =>
          (e.clientNames ?? []).some((n) => n.toLowerCase() === name)),
        unlogged: (Array.isArray(unlogged) ? unlogged : []).filter((u: UnloggedMeeting) =>
          (u.clientIds ?? []).includes(clientId)),
      });
    });
  }, [clientId, clientName]);

  if (data === null) return <Card className="p-5 text-sm text-gray-400">Loading calendar…</Card>;
  if (data.today.length === 0 && data.unlogged.length === 0) {
    return (
      <Card className="p-8 text-center">
        <Calendar className="mx-auto text-gray-300" size={26} />
        <p className="mt-3 text-sm font-medium text-gray-500">Nothing scheduled with this client</p>
        <p className="mt-1 text-xs text-gray-400">
          Meetings with this client (matched by attendee email) appear here. Schedule one from the{' '}
          <Link href="/butler/calendar" className="font-medium text-kora-600 hover:underline">Calendar</Link> tab.
        </p>
      </Card>
    );
  }
  return (
    <div className="space-y-4">
      {data.today.length > 0 && (
        <Card className="p-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Today</p>
          <ul className="space-y-2">
            {data.today.map((e) => (
              <li key={e.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-gray-800">{e.title}</span>
                <span className="flex items-center gap-3">
                  <span className="text-xs text-gray-400">{formatDate(e.start)}</span>
                  {e.meetLink && <a href={e.meetLink} target="_blank" rel="noreferrer" className="text-xs font-medium text-kora-600 hover:underline">Join</a>}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {data.unlogged.length > 0 && (
        <Card className="p-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Past — not logged</p>
          <ul className="space-y-2">
            {data.unlogged.map((u) => (
              <li key={u.eventId} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-gray-800">{u.title}</span>
                <span className="text-xs text-gray-400">{formatDate(u.date)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

const DRIVE_ICON: Record<string, typeof FileText> = {
  transcript: Video, contract: FileSignature, invoice: FileText, receipt: FileText, brief: FileText,
};

function DriveTab({ clientId }: { clientId: string }) {
  const [docs, setDocs] = useState<DriveDoc[] | null>(null);

  useEffect(() => {
    authedFetch(`/api/drive/cache?client_id=${clientId}`)
      .then((r) => r.json())
      .then((data) => setDocs(Array.isArray(data) ? data : []))
      .catch(() => setDocs([]));
  }, [clientId]);

  if (docs === null) return <Card className="p-5 text-sm text-gray-400">Loading files…</Card>;
  if (docs.length === 0) {
    return (
      <Card className="p-8 text-center">
        <HardDrive className="mx-auto text-gray-300" size={26} />
        <p className="mt-3 text-sm font-medium text-gray-500">No Drive files for this client</p>
        <p className="mt-1 text-xs text-gray-400">
          Scan Drive from the <Link href="/butler/drive" className="font-medium text-kora-600 hover:underline">Drive</Link> tab.
          Files that mention this client (by name or email) get linked here.
        </p>
      </Card>
    );
  }
  return (
    <Card className="divide-y divide-gray-100">
      {docs.map((d) => {
        const Icon = DRIVE_ICON[d.docType ?? ''] ?? FileText;
        return (
          <div key={d.driveFileId} className="flex items-center gap-3 px-5 py-3">
            <Icon size={16} className="shrink-0 text-gray-400" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-gray-800">{d.fileName ?? 'Untitled'}</p>
              <p className="mt-0.5 text-xs text-gray-400">{d.processedAt && formatDate(d.processedAt)}</p>
            </div>
            {d.docType && (
              <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-semibold capitalize text-gray-600">{d.docType}</span>
            )}
            {d.meetingId && (
              <Link href="/butler/meetings" className="shrink-0 text-xs font-medium text-kora-600 hover:underline">View meeting →</Link>
            )}
          </div>
        );
      })}
    </Card>
  );
}

function Overview({ detail }: { detail: ClientDetail }) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader title="Health signals" subtitle="Computed from your real data" />
        <div className="space-y-3 p-5">
          {detail.healthRisks.length === 0 && detail.healthPositives.length === 0 && (
            <p className="text-sm text-gray-500">No notable signals yet.</p>
          )}
          {detail.healthRisks.map((r, i) => (
            <p key={`r${i}`} className="flex items-start gap-2 text-sm text-gray-700">
              <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-500" /> {r}
            </p>
          ))}
          {detail.healthPositives.map((p, i) => (
            <p key={`p${i}`} className="flex items-start gap-2 text-sm text-gray-700">
              <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-emerald-500" /> {p}
            </p>
          ))}
        </div>
      </Card>
      <Card>
        <CardHeader title="Recent notes" />
        {detail.notes.length === 0 ? (
          <p className="px-5 py-6 text-sm text-gray-500">No notes yet. Use quick capture to log anything about this client.</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {detail.notes.slice(0, 5).map((n) => (
              <li key={n.id} className="px-5 py-3">
                <p className="text-sm text-gray-700">{n.contentMd}</p>
                <p className="mt-0.5 text-xs text-gray-400">
                  {humanize(n.noteType)} · {formatDate(n.createdAt)}{n.isAiGenerated && ' · via Kora'}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

const ENG_STATUS = ['planning', 'active', 'on_track', 'at_risk', 'paused', 'done', 'cancelled'];
const ENG_BADGE: Record<string, string> = {
  active: 'sent', on_track: 'paid', at_risk: 'warning', planning: 'info',
  paused: 'draft', done: 'success', cancelled: 'cancelled',
};

function Engagements({ detail }: { detail: ClientDetail }) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const [desc, setDesc] = useState('');
  const [type, setType] = useState('project');
  const [busy, setBusy] = useState(false);

  async function add() {
    if (!title.trim()) return;
    setBusy(true);
    try {
      await authedFetch(`/api/clients/${detail.id}/engagements`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), descriptionMd: desc.trim() || undefined, engagementType: type }),
      });
      setTitle(''); setDesc(''); setAdding(false);
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(e: Engagement, status: string) {
    await authedFetch(`/api/clients/${detail.id}/engagements/${e.id}`, {
      method: 'PATCH', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    router.refresh();
  }

  return (
    <Card>
      <CardHeader title="Engagements" subtitle="The work in flight — not a task manager"
        action={
          <button onClick={() => setAdding((a) => !a)} className="inline-flex items-center gap-1 rounded-md bg-kora-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-kora-700">
            <Plus size={13} /> Add
          </button>
        } />
      {adding && (
        <div className="space-y-3 border-b border-gray-100 bg-gray-50 p-5">
          <input className={input} placeholder="Engagement title — e.g. “Website redesign”" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea className={input} rows={2} placeholder="One sentence of context (optional)" value={desc} onChange={(e) => setDesc(e.target.value)} />
          <div className="flex items-center gap-2">
            <select className={input + ' max-w-[160px]'} value={type} onChange={(e) => setType(e.target.value)}>
              {['project', 'retainer', 'one_off', 'ongoing'].map((o) => <option key={o} value={o}>{humanize(o)}</option>)}
            </select>
            <button onClick={add} disabled={busy || !title.trim()} className="inline-flex items-center gap-1.5 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60">
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Add engagement
            </button>
          </div>
        </div>
      )}
      {detail.engagements.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <Briefcase className="text-gray-300" size={28} />
          <p className="mt-3 text-sm font-medium text-gray-900">No active engagements</p>
          <p className="mt-1 max-w-md text-sm text-gray-500">Add an engagement so Kora understands what work is happening. One sentence is enough.</p>
        </div>
      ) : (
        <ul className="divide-y divide-gray-100">
          {detail.engagements.map((e) => (
            <li key={e.id} className="flex items-center justify-between gap-3 px-5 py-3.5">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900">{e.title}</span>
                  <Badge value={ENG_BADGE[e.status] ?? 'info'} label={humanize(e.status)} />
                </div>
                {e.descriptionMd && <p className="mt-0.5 truncate text-xs text-gray-500">{e.descriptionMd}</p>}
              </div>
              <select value={e.status} onChange={(ev) => setStatus(e, ev.target.value)}
                className="shrink-0 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-600">
                {ENG_STATUS.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
              </select>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const NOTE_TYPES = ['general', 'meeting', 'call', 'email', 'decision', 'blocker', 'update'];

function Notes({ detail }: { detail: ClientDetail }) {
  const router = useRouter();
  const [content, setContent] = useState('');
  const [type, setType] = useState('general');
  const [busy, setBusy] = useState(false);

  async function add() {
    if (!content.trim()) return;
    setBusy(true);
    try {
      await authedFetch(`/api/clients/${detail.id}/notes`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ contentMd: content.trim(), noteType: type }),
      });
      setContent('');
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Notes" subtitle="Communication, meetings, blockers, decisions" />
      <div className="space-y-3 border-b border-gray-100 bg-gray-50 p-5">
        <textarea className={input} rows={2} placeholder="Add a note…" value={content} onChange={(e) => setContent(e.target.value)} />
        <div className="flex items-center gap-2">
          <select className={input + ' max-w-[150px]'} value={type} onChange={(e) => setType(e.target.value)}>
            {NOTE_TYPES.map((o) => <option key={o} value={o}>{humanize(o)}</option>)}
          </select>
          <button onClick={add} disabled={busy || !content.trim()} className="inline-flex items-center gap-1.5 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <NotebookPen size={14} />} Add note
          </button>
        </div>
      </div>
      {detail.notes.length === 0 ? (
        <p className="px-5 py-6 text-sm text-gray-500">No notes yet.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {detail.notes.map((n: ClientNote) => (
            <li key={n.id} className="px-5 py-3">
              <p className="text-sm text-gray-700">{n.contentMd}</p>
              <p className="mt-0.5 text-xs text-gray-400">
                {humanize(n.noteType)} · {formatDate(n.createdAt)}{n.isAiGenerated && ' · via Kora'}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Financials({ detail, cur }: { detail: ClientDetail; cur: string }) {
  const Section = ({ title, icon: Icon, items, empty, render }: any) => (
    <Card>
      <CardHeader title={title} />
      {items.length === 0 ? (
        <p className="px-5 py-5 text-sm text-gray-500">{empty}</p>
      ) : (
        <ul className="divide-y divide-gray-100">{items.map(render)}</ul>
      )}
    </Card>
  );
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Section title="Invoices" icon={FileText} items={detail.invoices} empty="No invoices linked."
        render={(i: any) => (
          <li key={i.id} className="flex items-center justify-between px-5 py-3">
            <span className="text-sm text-gray-700">{i.invoiceNumber}</span>
            <span className="flex items-center gap-2 text-sm">{formatMoney(i.total, cur)} <Badge value={i.status} /></span>
          </li>
        )} />
      <Section title="Contracts" icon={FileSignature} items={detail.contracts} empty="No contracts linked."
        render={(c: any) => (
          <li key={c.id} className="flex items-center justify-between px-5 py-3">
            <span className="truncate text-sm text-gray-700">{c.title ?? humanize(c.type)}</span>
            <Badge value={c.status} />
          </li>
        )} />
      <Section title="Proposals" icon={FileText} items={detail.proposals} empty="No proposals."
        render={(p: any) => (
          <li key={p.id} className="flex items-center justify-between px-5 py-3">
            <span className="truncate text-sm text-gray-700">{p.title}</span>
            <span className="flex items-center gap-2 text-sm">{formatMoney(p.totalAmount, cur)} <Badge value={p.status} /></span>
          </li>
        )} />
      <Section title="Retainers" icon={Repeat} items={detail.retainers} empty="No retainers."
        render={(r: any) => (
          <li key={r.id} className="flex items-center justify-between px-5 py-3">
            <span className="truncate text-sm text-gray-700">{r.title}</span>
            <span className="flex items-center gap-2 text-sm">{formatMoney(r.amount, cur)}/{r.billingCycle} <Badge value={r.status} /></span>
          </li>
        )} />
    </div>
  );
}
