'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Sparkles, Loader2, Check, X, AlertTriangle, TrendingUp, Target, Bot,
  Mail, Scale, Ban, CheckCircle2, ChevronRight,
} from 'lucide-react';
import { Card, CardHeader, StatCard } from '@/components/ui';
import { FormattedText } from '@/components/formatted-text';
import { authedFetch } from '@/lib/api/browser';
import { formatMoney } from '@/lib/utils';
import { cn } from '@/lib/utils';
import type { ManagerSnapshot, ManagerRun, ManagerTask, ManagerBriefing, Advisory } from '@/lib/api/types';
import { ManagerChat } from './manager-chat';

const KIND_ICON: Record<string, typeof Mail> = {
  send_followup: Mail,
  send_demand: Scale,
  writeoff_invoice: Ban,
};
const SEV: Record<string, string> = {
  critical: 'border-red-200 bg-red-50',
  warning: 'border-amber-200 bg-amber-50',
  info: 'border-gray-200 bg-white',
};

export function ManagerConsole({ snapshot }: { snapshot: ManagerSnapshot }) {
  const router = useRouter();
  const [briefing, setBriefing] = useState<ManagerBriefing | null>(snapshot.lastBriefing);
  const [autoActions, setAutoActions] = useState<string[]>([]);
  const [goal, setGoal] = useState(snapshot.goalProgress);
  const [stats, setStats] = useState(snapshot.stats);
  const [advisories, setAdvisories] = useState<Advisory[]>(snapshot.advisories ?? []);
  const [tasks, setTasks] = useState<ManagerTask[]>(snapshot.pendingTasks);
  const [running, setRunning] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [doneMsg, setDoneMsg] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    setDoneMsg(null);
    try {
      const res = await authedFetch('/api/manager/run', { method: 'POST' });
      const json = (await res.json()) as ManagerRun;
      if (!res.ok) throw new Error('Manager run failed');
      setBriefing(json.briefing);
      setAutoActions(json.autoActions);
      setGoal(json.goalProgress);
      setStats(json.stats);
      setAdvisories(json.advisories ?? []);
      setTasks(json.pendingTasks);
      router.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Manager run failed');
    } finally {
      setRunning(false);
    }
  }

  async function refreshSnapshot() {
    try {
      const res = await authedFetch('/api/manager');
      if (!res.ok) return;
      const j = await res.json();
      setTasks(j.pendingTasks);
      setStats(j.stats);
      setGoal(j.goalProgress);
      setAdvisories(j.advisories ?? []);
    } catch {
      /* ignore */
    }
  }

  async function decide(task: ManagerTask, action: 'approve' | 'dismiss') {
    setActing(task.id);
    setError(null);
    setDoneMsg(null);
    try {
      const res = await authedFetch(`/api/manager/tasks/${task.id}/${action}`, { method: 'POST' });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Action failed');
      setTasks((ts) => ts.filter((t) => t.id !== task.id));
      const verb = task.kind === 'send_demand' ? 'drafted the payment demand'
        : task.kind === 'writeoff_invoice' ? 'wrote off the invoice'
        : 'sent the follow-up';
      setDoneMsg(
        action === 'approve'
          ? `Approved — Kora ${verb} for ${(task.payload as any).invoiceNumber ?? 'the invoice'}.`
          : 'Dismissed.',
      );
      router.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Action failed');
    } finally {
      setActing(null);
    }
  }

  const pct =
    goal.monthlyGoal && goal.monthlyGoal > 0
      ? Math.min(100, Math.round((goal.monthIncome / goal.monthlyGoal) * 100))
      : null;

  return (
    <div className="space-y-6">
      {/* Briefing / run */}
      <Card>
        <div className="flex items-start gap-4 p-5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-kora-600 text-white">
            <Sparkles size={20} />
          </div>
          <div className="min-w-0 flex-1">
            {briefing ? (
              <>
                {briefing.statusLine && <p className="text-sm font-semibold text-gray-900">{briefing.statusLine}</p>}
                <FormattedText text={briefing.summary} className="mt-1 text-sm leading-relaxed text-gray-700" />
                {briefing.priorities.length > 0 && (
                  <ul className="mt-3 space-y-1.5">
                    {briefing.priorities.map((p, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                        <ChevronRight size={15} className="mt-0.5 shrink-0 text-kora-500" /> {p}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <>
                <p className="text-sm font-semibold text-gray-900">Your AI business manager</p>
                <p className="mt-1 text-sm text-gray-600">
                  Run a review and Kora will reconcile payments, refresh your forecast, and surface the
                  few decisions that need you — prioritized by your goals.
                </p>
              </>
            )}
            <button
              onClick={run}
              disabled={running}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
            >
              {running ? <Loader2 size={15} className="animate-spin" /> : <Bot size={15} />}
              {running ? 'Reviewing your business…' : briefing ? 'Re-run review' : 'Run manager'}
            </button>
          </div>
        </div>
        {autoActions.length > 0 && (
          <div className="border-t border-gray-100 bg-gray-50 px-5 py-3">
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">Handled automatically</p>
            <ul className="space-y-1">
              {autoActions.map((a, i) => (
                <li key={i} className="flex items-center gap-2 text-xs text-gray-600">
                  <CheckCircle2 size={13} className="text-emerald-500" /> {a}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {doneMsg && <div className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{doneMsg}</div>}

      {/* Goal + stats */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-5">
          <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-500">
            <Target size={13} /> Monthly goal
          </p>
          {goal.monthlyGoal ? (
            <>
              <p className="mt-2 text-2xl font-bold tabular-nums text-gray-900">
                {formatMoney(goal.monthIncome, stats.currency)}
                <span className="text-sm font-medium text-gray-400"> / {formatMoney(goal.monthlyGoal, stats.currency)}</span>
              </p>
              <div className="mt-2 h-2 w-full rounded-full bg-gray-100">
                <div className="h-2 rounded-full bg-kora-600" style={{ width: `${pct}%` }} />
              </div>
              <p className="mt-1 text-xs text-gray-400">{pct}% of goal this month</p>
            </>
          ) : (
            <>
              <p className="mt-2 text-2xl font-bold tabular-nums text-gray-900">{formatMoney(goal.monthIncome, stats.currency)}</p>
              <p className="mt-1 text-xs text-gray-400">
                Set a monthly goal in <a href="/settings" className="text-kora-600 hover:underline">Business profile</a> for progress tracking.
              </p>
            </>
          )}
        </Card>
        <StatCard
          label="Overdue"
          value={formatMoney(stats.overdueTotal, stats.currency)}
          hint={`${stats.overdueCount} invoice${stats.overdueCount === 1 ? '' : 's'}`}
          tone={stats.overdueCount > 0 ? 'red' : 'green'}
        />
        <StatCard
          label="Cash runway"
          value={stats.cashDangerDays != null ? `${stats.cashDangerDays} days` : 'Healthy'}
          hint={stats.currentBalance != null ? `Balance ${formatMoney(stats.currentBalance, stats.currency)}` : undefined}
          tone={stats.cashDangerDays != null ? 'amber' : 'green'}
        />
      </div>

      {/* Advisories — heads-up findings (no approval needed) */}
      {advisories.length > 0 && (
        <Card>
          <CardHeader title="Heads up" subtitle="Things worth knowing — no action required from you" />
          <ul className="divide-y divide-gray-100">
            {advisories.map((a, i) => (
              <li key={i} className="flex items-start gap-3 px-5 py-3.5">
                <AlertTriangle
                  size={16}
                  className={cn('mt-0.5 shrink-0', a.severity === 'critical' ? 'text-red-500' : a.severity === 'warning' ? 'text-amber-500' : 'text-gray-400')}
                />
                <div>
                  <p className="text-sm font-medium text-gray-900">{a.title}</p>
                  <p className="mt-0.5 text-xs text-gray-500">{a.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Approval queue */}
      <Card>
        <CardHeader title="Needs your decision" subtitle="Client-facing & irreversible actions wait for your approval" />
        {tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <CheckCircle2 className="text-emerald-500" size={28} />
            <p className="mt-3 text-sm font-medium text-gray-900">You&apos;re all caught up</p>
            <p className="mt-1 text-sm text-gray-500">Nothing needs your sign-off right now.</p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {tasks.map((t) => {
              const Icon = KIND_ICON[t.kind] ?? AlertTriangle;
              return (
                <li key={t.id} className={cn('flex items-start gap-3 px-5 py-4')}>
                  <div className={cn('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border', SEV[t.severity])}>
                    <Icon size={15} className={t.severity === 'critical' ? 'text-red-600' : t.severity === 'warning' ? 'text-amber-600' : 'text-gray-500'} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-gray-900">{t.title}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-gray-600">{t.rationale}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      onClick={() => decide(t, 'approve')}
                      disabled={acting === t.id}
                      className="inline-flex items-center gap-1 rounded-md bg-kora-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
                    >
                      {acting === t.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} Approve
                    </button>
                    <button
                      onClick={() => decide(t, 'dismiss')}
                      disabled={acting === t.id}
                      className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-60"
                    >
                      <X size={12} /> Dismiss
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {/* Conversational manager */}
      <ManagerChat onRunReview={run} onActed={refreshSnapshot} />
    </div>
  );
}
