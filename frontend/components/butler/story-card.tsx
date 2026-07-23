'use client';

import { useState } from 'react';
import {
  AlertTriangle, CheckCircle2, TrendingDown, Pencil, Loader2, X, Check, User, Sparkles,
} from 'lucide-react';
import { authedFetch } from '@/lib/api/browser';
import { formatDate, cn } from '@/lib/utils';
import type { Story, StoryObservation, ObservationKind } from '@/lib/api/types';

// A qualitative entry is considered stale once its evidence is this old, so an
// old judgement can never quietly read as current (M4 criterion 2).
const STALE_DAYS = 21;

const STORY_TONE: Record<string, string> = {
  todo: 'bg-gray-100 text-gray-600',
  in_progress: 'bg-blue-100 text-blue-700',
  blocked: 'bg-red-100 text-red-700',
  done: 'bg-emerald-100 text-emerald-700',
  cancelled: 'bg-gray-100 text-gray-400',
};

const KIND_META: Record<ObservationKind, { label: string; icon: typeof AlertTriangle; tone: string; dot: string }> = {
  blocker: { label: 'Blockers', icon: AlertTriangle, tone: 'text-red-600', dot: 'bg-red-400' },
  going_well: { label: "Going well", icon: CheckCircle2, tone: 'text-emerald-600', dot: 'bg-emerald-400' },
  not_going_well: { label: "Not going well", icon: TrendingDown, tone: 'text-amber-600', dot: 'bg-amber-400' },
};

// "from meeting", "from email"… so every judgement shows where it came from.
const SOURCE_VERB: Record<string, string> = {
  email: 'from email', meeting: 'from meeting', drive: 'from a document',
  task: 'from a task', invoice: 'from an invoice', agent: 'inferred by Kora', user: 'you noted',
};

function daysSince(iso: string): number {
  const ms = Date.now() - new Date(iso).getTime();
  return Math.max(0, Math.floor(ms / 86_400_000));
}

function progressTone(pct: number): string {
  return pct >= 80 ? 'bg-emerald-500' : pct >= 40 ? 'bg-blue-500' : 'bg-gray-300';
}

export function StoryCard({ story, onChanged }: { story: Story; onChanged?: () => void }) {
  const grouped: Record<ObservationKind, StoryObservation[]> = {
    blocker: [], going_well: [], not_going_well: [],
  };
  for (const o of story.observations) grouped[o.kind]?.push(o);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3.5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-gray-800">{story.title}</p>
        <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium capitalize', STORY_TONE[story.status])}>
          {story.status.replace(/_/g, ' ')}
        </span>
      </div>

      {/* Progress */}
      <div className="mt-2 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
          <div className={cn('h-full rounded-full transition-all', progressTone(story.progressPct))}
            style={{ width: `${story.progressPct}%` }} />
        </div>
        <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-gray-500">{story.progressPct}%</span>
      </div>

      {/* Observations, grouped by kind */}
      {story.observations.length > 0 && (
        <div className="mt-3 space-y-3">
          {(Object.keys(KIND_META) as ObservationKind[]).map((kind) =>
            grouped[kind].length === 0 ? null : (
              <div key={kind}>
                <p className={cn('mb-1 flex items-center gap-1 text-[11px] font-semibold', KIND_META[kind].tone)}>
                  <span className={cn('h-1.5 w-1.5 rounded-full', KIND_META[kind].dot)} />
                  {KIND_META[kind].label}
                </p>
                <ul className="space-y-1.5">
                  {grouped[kind].map((o) => (
                    <ObservationRow key={o.id} storyId={story.id} obs={o} onChanged={onChanged} />
                  ))}
                </ul>
              </div>
            ),
          )}
        </div>
      )}
    </div>
  );
}

function ObservationRow({
  storyId, obs, onChanged,
}: { storyId: string; obs: StoryObservation; onChanged?: () => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(obs.text);
  const [busy, setBusy] = useState(false);
  const age = daysSince(obs.observedAt);
  const stale = age >= STALE_DAYS;

  async function save() {
    if (!text.trim() || text.trim() === obs.text) { setEditing(false); return; }
    setBusy(true);
    try {
      const res = await authedFetch(`/api/stories/${storyId}/observations/${obs.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        // The API marks an edited observation user_edited + source=user, so the
        // nightly agent refresh will never overwrite it (M1 rule, M4 criterion 3).
        body: JSON.stringify({ kind: obs.kind, text: text.trim(), source: 'user', sourceRef: 'manual' }),
      });
      if (res.ok) { setEditing(false); onChanged?.(); }
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <li className="flex items-start gap-1.5">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          className="flex-1 rounded-md border border-kora-300 px-2 py-1 text-xs focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500"
        />
        <button onClick={save} disabled={busy} title="Save" className="mt-0.5 text-emerald-600 hover:text-emerald-700 disabled:opacity-50">
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
        </button>
        <button onClick={() => { setText(obs.text); setEditing(false); }} title="Cancel" className="mt-0.5 text-gray-400 hover:text-gray-600">
          <X size={13} />
        </button>
      </li>
    );
  }

  return (
    <li className="group flex items-start gap-1.5 text-xs text-gray-700">
      <span className="flex-1">
        {obs.text}
        <span className="ml-1.5 whitespace-nowrap text-[10px] text-gray-400">
          · {SOURCE_VERB[obs.source] ?? obs.source} · {formatDate(obs.observedAt)}
          {stale && (
            <span className="ml-1 rounded bg-amber-50 px-1 py-px font-medium text-amber-600" title={`Evidence is ${age} days old`}>
              stale · {age}d
            </span>
          )}
        </span>
        {/* Who owns this line — a human edit outranks the agent (M1). */}
        {obs.userEdited ? (
          <span className="ml-1 inline-flex items-center gap-0.5 rounded bg-kora-50 px-1 py-px text-[10px] font-medium text-kora-700" title="You edited this — the agent won't overwrite it">
            <User size={9} /> yours
          </span>
        ) : (
          <span className="ml-1 inline-flex items-center gap-0.5 text-[10px] text-gray-400" title="Written by Kora from evidence">
            <Sparkles size={9} /> Kora
          </span>
        )}
      </span>
      <button
        onClick={() => setEditing(true)}
        title="Edit"
        className="mt-0.5 shrink-0 text-gray-300 opacity-0 transition-opacity hover:text-kora-600 group-hover:opacity-100"
      >
        <Pencil size={11} />
      </button>
    </li>
  );
}
