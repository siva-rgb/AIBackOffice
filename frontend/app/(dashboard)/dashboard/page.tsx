import Link from 'next/link';
import { Bell, ArrowRight } from 'lucide-react';
import { serverGet } from '@/lib/api/server';
import type { Overview } from '@/lib/api/types';
import { Card, CardHeader, StatCard, Badge } from '@/components/ui';
import { BackendDown } from '@/components/backend-down';
import { RunDigestButton } from '@/components/run-digest-button';
import { formatMoney, formatDateTime, humanize } from '@/lib/utils';

export const dynamic = 'force-dynamic';

export default async function OverviewPage() {
  let data: Overview;
  try {
    data = await serverGet<Overview>('/api/overview');
  } catch {
    return <BackendDown />;
  }

  const { user, agentStats, unreadAlerts, recentActivity } = data;
  const cashTone = data.overdueCount >= 3 ? 'red' : data.overdueCount > 0 ? 'amber' : 'green';
  const cashLabel = data.overdueCount >= 3 ? 'At risk' : data.overdueCount > 0 ? 'Watch' : 'Healthy';

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">
          Good to see you, {user.fullName?.split(' ')[0] ?? 'there'}
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Kora is monitoring {user.businessName} 24/7. Here&apos;s what&apos;s happening.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Income this month" value={formatMoney(data.monthIncome, user.currency)} tone="green" />
        <StatCard label="Outstanding invoices" value={formatMoney(data.outstanding, user.currency)} hint={`${data.overdueCount} overdue`} tone={data.overdueCount ? 'amber' : 'default'} />
        <StatCard label="Cash flow status" value={cashLabel} tone={cashTone} />
        <StatCard label="AI actions logged" value={agentStats.total} hint={`${agentStats.today} today`} tone="brand" />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader title="Proactive alerts" subtitle={`${unreadAlerts.length} unread`} action={<RunDigestButton />} />
          <div className="divide-y divide-gray-100">
            {unreadAlerts.length === 0 && (
              <p className="px-5 py-6 text-sm text-gray-400">No alerts. Your business looks healthy.</p>
            )}
            {unreadAlerts.map((a) => (
              <div key={a.id} className="px-5 py-4">
                <div className="flex items-center gap-2">
                  <Bell size={14} className="text-gray-400" />
                  <Badge value={a.severity} />
                </div>
                <p className="mt-2 text-sm font-medium text-gray-900">{a.title}</p>
                <p className="mt-1 text-xs text-gray-500">{a.body}</p>
                {a.actionUrl && (
                  <Link href={a.actionUrl} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-kora-600">
                    {a.actionLabel ?? 'View'} <ArrowRight size={12} />
                  </Link>
                )}
              </div>
            ))}
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader
            title="Recent AI agent activity"
            subtitle="The last 6 autonomous actions"
            action={
              <Link href="/agents" className="text-xs font-medium text-kora-600">
                View all →
              </Link>
            }
          />
          <ul className="divide-y divide-gray-100">
            {recentActivity.map((l) => (
              <li key={l.id} className="flex items-center justify-between px-5 py-3.5">
                <div className="min-w-0">
                  <p className="truncate text-sm text-gray-900">{l.action}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {humanize(l.agentType)} · {formatDateTime(l.createdAt)}
                  </p>
                </div>
                <Badge value={l.triggeredBy} />
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
