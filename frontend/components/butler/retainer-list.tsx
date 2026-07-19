'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Plus, Loader2, Repeat, FileText } from 'lucide-react';
import { Card, CardHeader, Badge } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import { formatMoney, cn } from '@/lib/utils';
import type { Retainer, Client } from '@/lib/api/types';

const input =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';
const CYCLES = ['weekly', 'monthly', 'quarterly', 'annual'];

export function RetainerList({ retainers, clients }: { retainers: Retainer[]; clients: Client[] }) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  // form
  const [clientId, setClientId] = useState('');
  const [clientName, setClientName] = useState('');
  const [title, setTitle] = useState('');
  const [amount, setAmount] = useState('');
  const [cycle, setCycle] = useState('monthly');
  const [start, setStart] = useState(new Date().toISOString().slice(0, 10));

  const ready = title.trim() && Number(amount) > 0 && start && (clientId || clientName.trim());

  async function create() {
    setBusy('create');
    setMsg(null);
    try {
      const res = await authedFetch('/api/retainers', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          clientId: clientId || undefined,
          clientName: clientId ? undefined : clientName.trim() || undefined,
          title: title.trim(), amount: Number(amount), billingCycle: cycle, startDate: start,
        }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Could not create');
      setAdding(false); setTitle(''); setAmount(''); setClientName('');
      router.refresh();
    } catch (e: any) {
      setMsg(e?.message ?? 'Could not create');
    } finally {
      setBusy(null);
    }
  }

  async function invoiceNow(r: Retainer) {
    setBusy(r.id);
    setMsg(null);
    try {
      const res = await authedFetch(`/api/retainers/${r.id}/invoice`, { method: 'POST' });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Could not create invoice');
      setMsg(`Draft invoice ${json.invoiceNumber} created — review it in Invoices before sending.`);
      router.refresh();
    } catch (e: any) {
      setMsg(e?.message ?? 'Could not create invoice');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <Link href="/butler" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft size={15} /> Back to Butler
      </Link>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Retainers</h1>
          <p className="mt-1 text-sm text-gray-500">Recurring income. Kora drafts the invoice on each billing date and keeps your cash flow predictable.</p>
        </div>
        <button onClick={() => setAdding((a) => !a)} className="inline-flex items-center gap-1.5 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700">
          <Plus size={15} /> Add retainer
        </button>
      </div>

      {msg && <div className="rounded-lg bg-kora-50 px-4 py-3 text-sm text-kora-800">{msg}</div>}

      {adding && (
        <Card className="space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Client</label>
              {clients.length > 0 ? (
                <select className={input} value={clientId} onChange={(e) => setClientId(e.target.value)}>
                  <option value="">New / not listed…</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              ) : <p className="text-xs text-gray-400">No clients yet — enter a name.</p>}
            </div>
            {!clientId && (
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Client name</label>
                <input className={input} value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Blue Label LLC" />
              </div>
            )}
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">What is this retainer for?</label>
            <input className={input} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Monthly SEO" />
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Amount</label>
              <input type="number" className={input} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="1500" />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Billing cycle</label>
              <select className={input} value={cycle} onChange={(e) => setCycle(e.target.value)}>
                {CYCLES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Start date</label>
              <input type="date" className={input} value={start} onChange={(e) => setStart(e.target.value)} />
            </div>
          </div>
          <div className="flex justify-end">
            <button onClick={create} disabled={busy === 'create' || !ready}
              className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-5 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60">
              {busy === 'create' ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />} Add retainer
            </button>
          </div>
        </Card>
      )}

      <Card>
        {retainers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-14 text-center">
            <Repeat className="text-gray-300" size={30} />
            <p className="mt-3 text-sm font-medium text-gray-900">Retainers make your cash flow predictable</p>
            <p className="mt-1 max-w-md text-sm text-gray-500">
              Add a retainer and Kora drafts your invoice automatically on each billing date.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {retainers.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3 px-5 py-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-gray-900">{r.title}</span>
                    <Badge value={r.status === 'active' ? 'paid' : r.status === 'paused' ? 'warning' : 'cancelled'} label={r.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-gray-500">
                    {r.clientName ? `${r.clientName} · ` : ''}{formatMoney(r.amount, r.currency)} / {r.billingCycle}
                    {r.nextInvoiceDate && ` · next ${r.nextInvoiceDate}`}
                  </p>
                </div>
                <button onClick={() => invoiceNow(r)} disabled={busy === r.id || r.status !== 'active'}
                  className="inline-flex shrink-0 items-center gap-1 rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                  {busy === r.id ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />} Invoice now
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
