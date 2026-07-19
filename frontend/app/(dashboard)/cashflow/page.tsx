import { AlertTriangle, TrendingUp, Lightbulb } from 'lucide-react';
import { serverGet } from '@/lib/api/server';
import type { Forecast } from '@/lib/api/types';
import { Card, CardHeader, StatCard } from '@/components/ui';
import { BackendDown } from '@/components/backend-down';
import { ForecastChart } from '@/components/cashflow/forecast-chart';
import { formatMoney } from '@/lib/utils';

export const dynamic = 'force-dynamic';

export default async function CashflowPage() {
  let f: Forecast;
  try {
    f = await serverGet<Forecast>('/api/cashflow/forecast?horizon=90');
  } catch {
    return <BackendDown />;
  }

  const end = f.forecast[f.forecast.length - 1];
  const danger =
    f.dangerConservative14d != null || f.dangerExpected30d != null;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Cash flow</h1>
        <p className="mt-1 text-sm text-gray-500">
          90-day projection in three scenarios · refreshed by the forecast agent · {Math.round(f.confidenceScore * 100)}% confidence
        </p>
      </header>

      {danger && (
        <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-5 py-4">
          <AlertTriangle className="mt-0.5 text-red-500" size={18} />
          <div className="text-sm text-red-800">
            <p className="font-semibold">Cash flow warning</p>
            <p className="mt-0.5">
              {f.dangerConservative14d != null && `Conservative scenario turns negative in ~${f.dangerConservative14d} days. `}
              {f.dangerExpected30d != null && `Expected scenario turns negative in ~${f.dangerExpected30d} days.`}
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Current balance" value={formatMoney(f.currentBalance)} tone="brand" />
        <StatCard label="Expected in 90 days" value={formatMoney(end.expected)} tone={end.expected >= 0 ? 'green' : 'red'} />
        <StatCard label="Conservative in 90 days" value={formatMoney(end.conservative)} tone={end.conservative >= 0 ? 'green' : 'amber'} />
      </div>

      <Card>
        <CardHeader title="90-day forecast" subtitle="Optimistic · Expected · Conservative (running balance)" />
        <div className="p-5">
          <ForecastChart data={f.forecast} />
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Key risks" subtitle="Flagged by the AI forecast agent" />
          <ul className="space-y-2 p-5">
            {f.keyRisks.length === 0 && <li className="text-sm text-gray-400">No risks flagged.</li>}
            {f.keyRisks.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-500" /> {r}
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title="Recommended actions" subtitle="What Kora suggests you do" />
          <ul className="space-y-2 p-5">
            {f.recommendedActions.length === 0 && <li className="text-sm text-gray-400">Nothing urgent.</li>}
            {f.recommendedActions.map((a, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                <Lightbulb size={15} className="mt-0.5 shrink-0 text-kora-500" /> {a}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {f.assumptions.length > 0 && (
        <p className="text-xs text-gray-400">
          <TrendingUp size={12} className="mr-1 inline" />
          Assumptions: {f.assumptions.join(' · ')}
        </p>
      )}
    </div>
  );
}
