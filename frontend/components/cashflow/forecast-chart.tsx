'use client';

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from 'recharts';
import type { ForecastPoint } from '@/lib/api/types';
import { formatMoney } from '@/lib/utils';

export function ForecastChart({ data }: { data: ForecastPoint[] }) {
  // Thin to ~every 3rd point for a cleaner 90-day line.
  const points = data.filter((_, i) => i % 3 === 0 || i === data.length - 1);
  const fmtAxis = (v: number) =>
    Math.abs(v) >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v.toFixed(0)}`;
  const fmtDate = (d: string) => d.slice(5); // MM-DD

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 10, right: 16, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef0f4" />
          <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 11, fill: '#94a3b8' }} minTickGap={28} />
          <YAxis tickFormatter={fmtAxis} tick={{ fontSize: 11, fill: '#94a3b8' }} width={48} />
          <Tooltip
            formatter={(v: number, name: string) => [formatMoney(v), name]}
            labelFormatter={(l) => `Date: ${l}`}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
          />
          <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 4" />
          <Line type="monotone" dataKey="optimistic" name="Optimistic" stroke="#10b981" strokeWidth={1.5} dot={false} />
          <Line type="monotone" dataKey="expected" name="Expected" stroke="#2f6fed" strokeWidth={2.5} dot={false} />
          <Line type="monotone" dataKey="conservative" name="Conservative" stroke="#f59e0b" strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
