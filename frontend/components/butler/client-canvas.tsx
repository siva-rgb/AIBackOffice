'use client';

import { useEffect, useState, useCallback } from 'react';
import {
  RefreshCw, Loader2, Truck, DollarSign, HeartHandshake, ShieldAlert,
  AlertTriangle, CheckCircle2, Sparkles,
} from 'lucide-react';
import { Card } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import { formatDateTime, formatMoney, humanize, cn } from '@/lib/utils';
import type { ClientView, ClientViewSection } from '@/lib/api/types';

function healthTone(score: number): string {
  return score >= 75 ? 'text-emerald-600' : score >= 55 ? 'text-amber-600' : 'text-red-600';
}

// The composed one-pager (M3). Numbers here come from the ledger; the prose is
// analyst-written and figure-checked server-side, so nothing shown is invented.
const SECTION_META: Record<string, { title: string; icon: typeof Truck; tone: string }> = {
  delivery: { title: 'Delivery', icon: Truck, tone: 'text-blue-500' },
  money: { title: 'Money', icon: DollarSign, tone: 'text-emerald-500' },
  relationship: { title: 'Relationship', icon: HeartHandshake, tone: 'text-fuchsia-500' },
  risk: { title: 'Risk', icon: ShieldAlert, tone: 'text-amber-500' },
};
const SECTION_ORDER = ['delivery', 'money', 'relationship', 'risk'] as const;

export function ClientCanvas({ clientId }: { clientId: string }) {
  const [view, setView] = useState<ClientView | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await authedFetch(`/api/clients/${clientId}/view`);
      setView(res.ok ? await res.json() : null);
    } catch {
      setView(null);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function refresh() {
    setRefreshing(true);
    try {
      const res = await authedFetch(`/api/clients/${clientId}/view/refresh`, { method: 'POST' });
      if (res.ok) setView(await res.json());
    } finally {
      setRefreshing(false);
    }
  }

  if (loading) {
    return (
      <Card className="flex items-center justify-center gap-2 p-8 text-sm text-gray-400">
        <Loader2 size={16} className="animate-spin" /> Loading the client picture…
      </Card>
    );
  }
  if (!view) {
    return <Card className="p-6 text-sm text-gray-500">Couldn’t load this client’s view.</Card>;
  }

  return (
    <div className="space-y-4">
      {/* Freshness + refresh control */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">
          {view.stale ? (
            <span className="inline-flex items-center gap-1 text-amber-600">
              <AlertTriangle size={12} /> Not composed yet — showing live numbers only
            </span>
          ) : view.refreshedAt ? (
            <>Composed {formatDateTime(view.refreshedAt)}</>
          ) : null}
        </p>
        <button onClick={refresh} disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:border-kora-300 hover:text-kora-700 disabled:opacity-50">
          {refreshing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          {refreshing ? 'Composing…' : 'Ask Kora to refresh'}
        </button>
      </div>

      {/* Client-level roll-up — the top of the pyramid, computed server-side */}
      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">Client health</p>
            <div className="mt-1 flex items-baseline gap-2">
              <span className={cn('text-3xl font-bold tabular-nums', healthTone(view.headline.healthScore))}>
                {view.headline.healthScore}
              </span>
              <span className="text-sm text-gray-500">{humanize(view.headline.healthLabel)}</span>
            </div>
          </div>
          <div className="flex gap-6">
            <div className="text-right">
              <p className="text-[11px] uppercase tracking-wide text-gray-400">Delivery</p>
              <p className="text-lg font-semibold tabular-nums text-gray-900">{view.headline.progressPct}%</p>
            </div>
            <div className="text-right">
              <p className="text-[11px] uppercase tracking-wide text-gray-400">Outstanding</p>
              <p className="text-lg font-semibold tabular-nums text-gray-900">{formatMoney(view.headline.outstanding)}</p>
            </div>
            <div className="text-right">
              <p className="text-[11px] uppercase tracking-wide text-gray-400">Blockers</p>
              <p className={cn('text-lg font-semibold tabular-nums', view.headline.openBlockers > 0 ? 'text-red-600' : 'text-gray-900')}>
                {view.headline.openBlockers}
              </p>
            </div>
          </div>
        </div>
      </Card>

      {/* Sections — Delivery · Money · Relationship · Risk */}
      <div className="grid gap-4 lg:grid-cols-2">
        {SECTION_ORDER.map((key) => (
          <SectionCard key={key} sectionKey={key} section={view.sections[key]} />
        ))}
      </div>

      {view.degradedSections.length > 0 && !view.stale && (
        <p className="text-[11px] text-gray-400">
          {view.degradedSections.length} section(s) fell back to plain numbers this run — the rest
          were composed by Kora.
        </p>
      )}
    </div>
  );
}

function SectionCard({ sectionKey, section }: { sectionKey: string; section: ClientViewSection }) {
  const meta = SECTION_META[sectionKey];
  const Icon = meta.icon;
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2">
        <Icon size={16} className={meta.tone} />
        <h3 className="text-sm font-semibold text-gray-900">{meta.title}</h3>
        {!section.degraded && (
          <span className="ml-auto inline-flex items-center gap-0.5 text-[10px] text-gray-400" title="Written by Kora from verified numbers">
            <Sparkles size={10} /> Kora
          </span>
        )}
      </div>

      <p className="mt-2 text-sm text-gray-700">{section.summary}</p>

      {section.highlights.length > 0 && (
        <ul className="mt-2.5 space-y-1">
          {section.highlights.map((h, i) => (
            <li key={`h${i}`} className="flex items-start gap-1.5 text-xs text-gray-600">
              <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-emerald-500" /> {h}
            </li>
          ))}
        </ul>
      )}
      {section.concerns.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {section.concerns.map((c, i) => (
            <li key={`c${i}`} className="flex items-start gap-1.5 text-xs text-gray-600">
              <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-500" /> {c}
            </li>
          ))}
        </ul>
      )}

      <SectionMetrics sectionKey={sectionKey} metrics={section.metrics} />
    </Card>
  );
}

// Render just the headline figures we know each section carries — always the
// ledger's numbers, never anything the model produced.
function SectionMetrics({ sectionKey, metrics }: { sectionKey: string; metrics: Record<string, unknown> }) {
  const chips: string[] = [];
  const n = (k: string) => (typeof metrics[k] === 'number' ? (metrics[k] as number) : undefined);

  if (sectionKey === 'delivery') {
    if (n('progressPct') !== undefined) chips.push(`${n('progressPct')}% complete`);
    if (n('blockerCount')) chips.push(`${n('blockerCount')} blocker(s)`);
    if (n('overdueTasks')) chips.push(`${n('overdueTasks')} overdue`);
  } else if (sectionKey === 'money') {
    if (n('outstanding') !== undefined) chips.push(`$${(n('outstanding') ?? 0).toLocaleString()} outstanding`);
    if (n('overdueCount')) chips.push(`${n('overdueCount')} overdue invoice(s)`);
  } else if (sectionKey === 'relationship') {
    const s = n('silentDays');
    if (s !== undefined) chips.push(`${s}d since activity`);
  } else if (sectionKey === 'risk') {
    if (n('deliveryScore') !== undefined) chips.push(`delivery ${n('deliveryScore')}/100`);
    if (n('notGoingWellCount')) chips.push(`${n('notGoingWellCount')} flagged`);
  }

  if (chips.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1.5 border-t border-gray-100 pt-2.5">
      {chips.map((c, i) => (
        <span key={i} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-gray-600">
          {c}
        </span>
      ))}
    </div>
  );
}
