'use client';

import { useMemo, useState } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import { ChevronDown, Download } from 'lucide-react';
import { Card, CardHeader, Badge } from '@/components/ui';
import { FormattedText } from '@/components/formatted-text';
import { formatDateTime, humanize } from '@/lib/utils';
import { DownloadButton } from '@/components/download-button';

export interface LogVM {
  id: string;
  agentType: string;
  action: string;
  triggeredBy: string;
  status: string;
  modelUsed: string;
  tokensUsed: number | null;
  latencyMs: number | null;
  costUsd: number | null;
  createdAt: string;
  input: unknown;
  output: unknown;
}

const COLORS = ['#2f6fed', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#64748b'];

export function AgentExplorer({ logs }: { logs: LogVM[] }) {
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [triggerFilter, setTriggerFilter] = useState<string>('all');
  const [expanded, setExpanded] = useState<string | null>(null);

  const types = useMemo(() => Array.from(new Set(logs.map((l) => l.agentType))), [logs]);

  const byType = useMemo(() => {
    const m: Record<string, number> = {};
    for (const l of logs) m[l.agentType] = (m[l.agentType] ?? 0) + 1;
    return Object.entries(m).map(([name, value]) => ({ name: humanize(name), value }));
  }, [logs]);

  const filtered = logs.filter(
    (l) =>
      (typeFilter === 'all' || l.agentType === typeFilter) &&
      (triggerFilter === 'all' || l.triggeredBy === triggerFilter),
  );

  const selectClass =
    'rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-kora-500 focus:outline-none';

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <CardHeader title="Actions by agent" subtitle="All-time distribution" />
        <div className="p-5">
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={byType} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={2}>
                  {byType.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="mt-3 space-y-1.5">
            {byType.map((d, i) => (
              <li key={d.name} className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-2 text-gray-600">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
                  {d.name}
                </span>
                <span className="font-medium tabular-nums text-gray-900">{d.value}</span>
              </li>
            ))}
          </ul>
        </div>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader
          title="Execution log"
          subtitle={`${filtered.length} of ${logs.length} actions`}
          action={
            <DownloadButton
              path="/api/agents/log/export"
              filename="kora-agent-logs.csv"
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              <Download size={13} /> Export CSV
            </DownloadButton>
          }
        />
        <div className="flex flex-wrap gap-3 border-b border-gray-100 px-5 py-3">
          <select className={selectClass} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="all">All agents</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {humanize(t)}
              </option>
            ))}
          </select>
          <select className={selectClass} value={triggerFilter} onChange={(e) => setTriggerFilter(e.target.value)}>
            <option value="all">All triggers</option>
            <option value="user">User</option>
            <option value="scheduler">Scheduler</option>
            <option value="cross_module">Cross-module</option>
            <option value="webhook">Webhook</option>
          </select>
        </div>

        <ul className="kora-scroll max-h-[520px] divide-y divide-gray-100 overflow-y-auto">
          {filtered.map((l) => {
            const isOpen = expanded === l.id;
            return (
              <li key={l.id}>
                <button
                  onClick={() => setExpanded(isOpen ? null : l.id)}
                  className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-gray-50"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm text-gray-900">{l.action}</p>
                    <p className="mt-0.5 flex items-center gap-2 text-xs text-gray-400">
                      <span>{humanize(l.agentType)}</span>·<span>{formatDateTime(l.createdAt)}</span>
                      {l.latencyMs != null && <>·<span>{l.latencyMs}ms</span></>}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge value={l.triggeredBy} />
                    <Badge value={l.status} />
                    <ChevronDown size={15} className={isOpen ? 'rotate-180 text-gray-400 transition' : 'text-gray-400 transition'} />
                  </div>
                </button>
                {isOpen && (
                  <div className="space-y-3 bg-gray-50 px-5 py-4 text-xs">
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <Meta label="Model" value={l.modelUsed} />
                      <Meta label="Tokens" value={l.tokensUsed ?? '—'} />
                      <Meta label="Latency" value={l.latencyMs != null ? `${l.latencyMs}ms` : '—'} />
                      <Meta label="Est. cost" value={l.costUsd != null ? `$${l.costUsd.toFixed(4)}` : '—'} />
                    </div>
                    <JsonBlock label="Input" value={l.input} />
                    <OutputBlock value={l.output} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-0.5 font-medium text-gray-800">{value}</p>
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <p className="mb-1 text-[10px] uppercase tracking-wide text-gray-400">{label}</p>
      <pre className="kora-scroll max-h-44 overflow-auto rounded-lg border border-gray-200 bg-white p-3 font-mono text-[11px] leading-relaxed text-gray-700">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

// Email-shaped outputs (drafted/sent follow-ups, demand letters) render as a
// readable preview; any other output shape falls back to the raw JSON.
function OutputBlock({ value }: { value: unknown }) {
  const obj = value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
  const body = obj && typeof obj.body === 'string' ? (obj.body as string) : null;
  if (!body) return <JsonBlock label="Output" value={value} />;

  const subject = obj && typeof obj.subject === 'string' ? (obj.subject as string) : null;
  const delivered = obj ? obj.delivered === true : false;
  return (
    <div>
      <p className="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-wide text-gray-400">
        Output
        <span
          className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${delivered ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-200 text-gray-600'}`}
        >
          {delivered ? 'Sent' : 'Draft'}
        </span>
      </p>
      <div className="kora-scroll max-h-72 overflow-auto rounded-lg border border-gray-200 bg-white p-3">
        {subject && <p className="mb-2 text-sm font-semibold text-gray-900">{subject}</p>}
        <FormattedText text={body} className="text-[13px] leading-relaxed text-gray-700" />
      </div>
    </div>
  );
}
