'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Sparkles, Loader2, Bot, ChevronRight, Plus, FileText, Repeat, Users,
  TrendingUp, AlertCircle, ArrowRight, Mail,
} from 'lucide-react';
import { Card, CardHeader, StatCard, Badge } from '@/components/ui';
import { FormattedText } from '@/components/formatted-text';
import { authedFetch } from '@/lib/api/browser';
import { formatMoney, cn } from '@/lib/utils';
import type { ButlerSnapshot, ButlerBriefing, ButlerRun, Client } from '@/lib/api/types';

const TONE_DOT: Record<string, string> = {
  energetic: 'bg-emerald-500',
  steady: 'bg-gray-400',
  cautious: 'bg-amber-500',
};

function HealthDot({ score }: { score: number }) {
  const color = score >= 75 ? 'bg-emerald-500' : score >= 50 ? 'bg-amber-500' : 'bg-red-500';
  return <span className={cn('inline-block h-2.5 w-2.5 rounded-full', color)} />;
}

export function ButlerHome({
  snapshot,
  clients,
}: {
  snapshot: ButlerSnapshot;
  clients: Client[];
}) {
  const router = useRouter();
  const [briefing, setBriefing] = useState<ButlerBriefing | null>(snapshot.lastBriefing ?? null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cur = snapshot.stats.currency;

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const res = await authedFetch('/api/butler/run', { method: 'POST' });
      const json = (await res.json()) as ButlerRun;
      if (!res.ok) throw new Error('Briefing failed');
      setBriefing(json.briefing);
      router.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Briefing failed');
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Morning briefing */}
      <Card>
        <div className="flex items-start gap-4 p-5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-kora-600 text-white">
            <Sparkles size={20} />
          </div>
          <div className="min-w-0 flex-1">
            {briefing ? (
              <>
                <div className="flex items-center gap-2">
                  <span className={cn('h-2 w-2 rounded-full', TONE_DOT[briefing.tone] ?? 'bg-gray-400')} />
                  <p className="text-sm font-semibold text-gray-900">{briefing.headline}</p>
                </div>
                <FormattedText text={briefing.twoSentenceSummary} className="mt-1.5 text-sm leading-relaxed text-gray-700" />
                {briefing.keyInsight && (
                  <p className="mt-2 rounded-lg bg-kora-50 px-3 py-2 text-xs text-kora-800">
                    💡 {briefing.keyInsight}
                  </p>
                )}
                {briefing.focusToday.length > 0 && (
                  <div className="mt-3">
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Focus today</p>
                    <ul className="space-y-1.5">
                      {briefing.focusToday.map((f, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                          <ChevronRight size={15} className="mt-0.5 shrink-0 text-kora-500" /> {f}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {(briefing.goingWell || briefing.watchOut) && (
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    {briefing.goingWell && (
                      <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2">
                        <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-600">Going well</p>
                        <p className="mt-0.5 text-xs text-emerald-800">{briefing.goingWell}</p>
                      </div>
                    )}
                    {briefing.watchOut && (
                      <div className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2">
                        <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-600">Watch out</p>
                        <p className="mt-0.5 text-xs text-amber-800">{briefing.watchOut}</p>
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              <>
                <p className="text-sm font-semibold text-gray-900">Your morning briefing will appear here</p>
                <p className="mt-1 text-sm text-gray-600">
                  Kora reviews your clients, work, and money each morning and tells you what matters most.
                  Run it now to see your first briefing.
                </p>
              </>
            )}
            <button
              onClick={run}
              disabled={running}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
            >
              {running ? <Loader2 size={15} className="animate-spin" /> : <Bot size={15} />}
              {running ? 'Reviewing your business…' : briefing ? 'Refresh briefing' : 'Run briefing'}
            </button>
          </div>
        </div>
      </Card>

      {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-4">
        <StatCard label="Active clients" value={snapshot.stats.clientCount} tone="brand" />
        <StatCard label="Engagements" value={snapshot.stats.activeEngagements}
          hint={snapshot.stats.atRiskEngagements > 0 ? `${snapshot.stats.atRiskEngagements} at risk` : 'on track'}
          tone={snapshot.stats.atRiskEngagements > 0 ? 'amber' : 'green'} />
        <StatCard label="Overdue" value={formatMoney(snapshot.stats.overdueTotal, cur)}
          hint={`${snapshot.stats.overdueCount} invoice${snapshot.stats.overdueCount === 1 ? '' : 's'}`}
          tone={snapshot.stats.overdueCount > 0 ? 'red' : 'green'} />
        <StatCard label="To review" value={snapshot.reviewQueueCount}
          hint="captures flagged" tone={snapshot.reviewQueueCount > 0 ? 'amber' : 'default'} />
      </div>

      {/* Quick links */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Link href="/butler/proposals" className="group flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm hover:border-kora-300">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600"><FileText size={17} /></div>
            <div><p className="text-sm font-semibold text-gray-900">Proposals</p><p className="text-xs text-gray-500">Win work, then turn it into a contract</p></div>
          </div>
          <ArrowRight size={16} className="text-gray-300 group-hover:text-kora-500" />
        </Link>
        <Link href="/butler/retainers" className="group flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm hover:border-kora-300">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600"><Repeat size={17} /></div>
            <div><p className="text-sm font-semibold text-gray-900">Retainers</p><p className="text-xs text-gray-500">Recurring income, auto-invoiced</p></div>
          </div>
          <ArrowRight size={16} className="text-gray-300 group-hover:text-kora-500" />
        </Link>
      </div>

      {/* Client health list */}
      <Card>
        <CardHeader
          title="Clients"
          subtitle="Health reflects overdue money, stalled work, and silence"
          action={
            <Link href="/butler/clients/new" className="inline-flex items-center gap-1 rounded-md bg-kora-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-kora-700">
              <Plus size={13} /> Add client
            </Link>
          }
        />
        {clients.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-14 text-center">
            <Users className="text-gray-300" size={30} />
            <p className="mt-3 text-sm font-medium text-gray-900">Kora is ready — add your first client</p>
            <p className="mt-1 max-w-md text-sm text-gray-500">
              Once you add a client, Kora monitors the relationship — flagging overdue invoices, stalled work,
              and long silences before they become problems.
            </p>
            <Link href="/butler/clients/new" className="mt-4 inline-flex items-center gap-1 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700">
              <Plus size={14} /> Add first client
            </Link>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {clients.map((c) => (
              <li key={c.id} className="flex items-center hover:bg-gray-50">
                <Link href={`/butler/clients/${c.id}`} className="flex min-w-0 flex-1 items-center gap-3 py-3.5 pl-5">
                  <HealthDot score={c.healthScore} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-gray-900">{c.name}</span>
                      <Badge value={c.status} />
                    </div>
                    <p className="mt-0.5 truncate text-xs text-gray-500">
                      {c.whatWeDo ?? c.company ?? c.clientType}
                      {(c.activeEngagementCount ?? 0) > 0 && ` · ${c.activeEngagementCount} engagement${c.activeEngagementCount === 1 ? '' : 's'}`}
                    </p>
                  </div>
                  <div className="hidden text-right sm:block">
                    {c.financials && c.financials.outstanding > 0 ? (
                      <p className="text-sm font-medium text-red-600">{formatMoney(c.financials.outstanding, cur)} due</p>
                    ) : c.financials && c.financials.paid > 0 ? (
                      <p className="text-sm font-medium text-emerald-600">{formatMoney(c.financials.paid, cur)} paid</p>
                    ) : (
                      <p className="text-xs text-gray-400">No invoices</p>
                    )}
                    <p className="text-xs text-gray-400">
                      {c.daysSinceActivity != null ? `${c.daysSinceActivity}d since activity` : '—'}
                    </p>
                  </div>
                </Link>
                <Link
                  href={`/butler/clients/${c.id}?tab=email`}
                  title="Ask Butler to draft an email"
                  className="mx-2 shrink-0 rounded-md p-2 text-gray-400 hover:bg-kora-50 hover:text-kora-600"
                >
                  <Mail size={16} />
                </Link>
                <ChevronRight size={16} className="mr-4 shrink-0 text-gray-300" />
              </li>
            ))}
          </ul>
        )}
      </Card>

      {snapshot.reviewQueueCount > 0 && (
        <Card className="border-amber-200">
          <div className="flex items-center gap-3 px-5 py-4">
            <AlertCircle size={18} className="shrink-0 text-amber-500" />
            <p className="flex-1 text-sm text-gray-700">
              {snapshot.reviewQueueCount} quick capture{snapshot.reviewQueueCount === 1 ? '' : 's'} need your review —
              Kora wasn&apos;t confident where {snapshot.reviewQueueCount === 1 ? 'it' : 'they'} belonged.
            </p>
            <Link href="/butler/capture" className="inline-flex items-center gap-1 rounded-md border border-amber-300 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50">
              <TrendingUp size={13} /> Review
            </Link>
          </div>
        </Card>
      )}
    </div>
  );
}
