import { Bot } from 'lucide-react';
import { serverGet } from '@/lib/api/server';
import type { AgentLog, AgentStats } from '@/lib/api/types';
import { StatCard, Card } from '@/components/ui';
import { BackendDown } from '@/components/backend-down';
import { AgentExplorer, type LogVM } from '@/components/agents/agent-explorer';

export const dynamic = 'force-dynamic';

export default async function AgentsPage() {
  let logs: AgentLog[];
  let stats: AgentStats;
  try {
    [logs, stats] = await Promise.all([
      serverGet<AgentLog[]>('/api/agents/log'),
      serverGet<AgentStats>('/api/agents/log/stats'),
    ]);
  } catch {
    return <BackendDown />;
  }

  const vms: LogVM[] = logs.map((l) => ({
    id: l.id,
    agentType: l.agentType,
    action: l.action,
    triggeredBy: l.triggeredBy,
    status: l.status,
    modelUsed: l.modelUsed,
    tokensUsed: l.tokensUsed,
    latencyMs: l.latencyMs,
    costUsd: l.costUsd,
    createdAt: l.createdAt,
    input: l.input,
    output: l.output,
  }));

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">AI Agents</h1>
        <p className="mt-1 text-sm text-gray-500">
          Every autonomous decision Kora has made on your behalf — the full audit trail.
        </p>
      </header>

      {logs.length === 0 ? (
        <Card className="flex flex-col items-center justify-center py-16 text-center">
          <Bot className="text-kora-600" size={32} />
          <h2 className="mt-4 text-lg font-semibold text-gray-900">AI agents are standing by</h2>
          <p className="mt-1 max-w-sm text-sm text-gray-500">
            Every action Kora takes appears here. Upload transactions or run the follow-up agent to
            see the first one.
          </p>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Total AI actions" value={stats.total} hint="all time" tone="brand" />
            <StatCard label="Today / this week" value={`${stats.today} / ${stats.thisWeek}`} />
            <StatCard label="Success rate" value={`${stats.successRate}%`} hint={`avg ${stats.avgLatencyMs}ms`} tone="green" />
            <StatCard label="Est. AI spend" value={`$${stats.totalCostUsd.toFixed(4)}`} hint="cumulative" />
          </div>
          <AgentExplorer logs={vms} />
        </>
      )}
    </div>
  );
}
