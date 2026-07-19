import { Download, AlertTriangle, UploadCloud } from 'lucide-react';
import { serverGet } from '@/lib/api/server';
import type { Transaction, Pnl } from '@/lib/api/types';
import { Card, CardHeader, StatCard, Badge } from '@/components/ui';
import { BackendDown } from '@/components/backend-down';
import { DownloadButton } from '@/components/download-button';
import { UploadZone } from '@/components/bookkeeping/upload-zone';
import { formatMoney, formatDate, humanize } from '@/lib/utils';

export const dynamic = 'force-dynamic';

const LOW_CONFIDENCE = 0.7;

export default async function BookkeepingPage() {
  let txns: Transaction[];
  let pnl: Pnl;
  try {
    [txns, pnl] = await Promise.all([
      serverGet<Transaction[]>('/api/bookkeeping/transactions'),
      serverGet<Pnl>('/api/bookkeeping/pnl'),
    ]);
  } catch {
    return <BackendDown />;
  }

  const currency = txns[0]?.currency ?? 'USD';
  const lowConf = txns.filter((t) => t.aiConfidence != null && t.aiConfidence < LOW_CONFIDENCE);

  return (
    <div className="space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Bookkeeping</h1>
          <p className="mt-1 text-sm text-gray-500">
            {txns.length} transactions · AI-categorized automatically
          </p>
        </div>
        {txns.length > 0 && (
          <DownloadButton
            path="/api/bookkeeping/report"
            filename="kora-pnl.pdf"
            className="rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700"
          >
            <Download size={16} /> Download P&amp;L PDF
          </DownloadButton>
        )}
      </header>

      {txns.length === 0 ? (
        <Card className="flex flex-col items-center justify-center py-16 text-center">
          <UploadCloud className="text-kora-600" size={32} />
          <h2 className="mt-4 text-lg font-semibold text-gray-900">Upload your first bank statement</h2>
          <p className="mt-1 max-w-sm text-sm text-gray-500">
            Kora&apos;s AI will categorize every transaction and generate your P&amp;L report.
          </p>
          <div className="mt-6 w-full max-w-md">
            <UploadZone />
          </div>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Total income" value={formatMoney(pnl.totalIncome, currency)} tone="green" />
            <StatCard label="Total expenses" value={formatMoney(pnl.totalExpenses, currency)} tone="red" />
            <StatCard label="Net profit" value={formatMoney(pnl.netProfit, currency)} hint={`${pnl.profitMargin}% margin`} tone={pnl.netProfit >= 0 ? 'green' : 'red'} />
            <StatCard label="Tax-deductible" value={formatMoney(pnl.deductibleExpenses, currency)} tone="brand" />
          </div>

          <Card>
            <CardHeader title="Import more transactions" subtitle="Drag a CSV — new rows are deduplicated and categorized" />
            <div className="p-5">
              <UploadZone />
            </div>
          </Card>

          {lowConf.length > 0 && (
            <Card>
              <CardHeader
                title="Review queue"
                subtitle={`${lowConf.length} transactions categorized below ${LOW_CONFIDENCE * 100}% confidence`}
              />
              <ul className="divide-y divide-gray-100">
                {lowConf.map((t) => (
                  <li key={t.id} className="flex items-center justify-between px-5 py-3">
                    <div className="flex items-center gap-2">
                      <AlertTriangle size={15} className="text-amber-500" />
                      <div>
                        <p className="text-sm text-gray-900">{t.description}</p>
                        <p className="text-xs text-gray-400">
                          {formatDate(t.date)} · suggested: {humanize(t.category)} ·{' '}
                          {Math.round((t.aiConfidence ?? 0) * 100)}% confidence
                        </p>
                      </div>
                    </div>
                    <span className="tabular-nums text-sm font-medium text-gray-900">
                      {formatMoney(t.amount, t.currency)}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card>
            <CardHeader title="Transactions" subtitle="Most recent first" />
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-xs uppercase tracking-wide text-gray-400">
                    <th className="px-5 py-3 font-medium">Date</th>
                    <th className="px-5 py-3 font-medium">Description</th>
                    <th className="px-5 py-3 font-medium">Category</th>
                    <th className="px-5 py-3 font-medium">Deductible</th>
                    <th className="px-5 py-3 text-right font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {txns.slice(0, 60).map((t) => (
                    <tr key={t.id} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-5 py-3 text-gray-500">{formatDate(t.date)}</td>
                      <td className="px-5 py-3 text-gray-900">{t.description}</td>
                      <td className="px-5 py-3">
                        <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                          {humanize(t.category)}
                        </span>
                      </td>
                      <td className="px-5 py-3">
                        {t.taxDeductible ? <Badge value="success" label="Yes" /> : <span className="text-xs text-gray-400">—</span>}
                      </td>
                      <td className={`whitespace-nowrap px-5 py-3 text-right font-medium tabular-nums ${t.type === 'income' ? 'text-emerald-600' : 'text-gray-900'}`}>
                        {formatMoney(t.amount, t.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
