'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Loader2, Sparkles } from 'lucide-react';
import { Card } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import { cn } from '@/lib/utils';
import type { Client, Proposal } from '@/lib/api/types';

const input =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';

const PRICING = ['fixed', 'hourly', 'retainer', 'milestone'];

export function ProposalWizard({ clients }: { clients: Client[] }) {
  const router = useRouter();
  const [clientId, setClientId] = useState('');
  const [clientName, setClientName] = useState('');
  const [title, setTitle] = useState('');
  const [scope, setScope] = useState('');
  const [deliverables, setDeliverables] = useState('');
  const [timeline, setTimeline] = useState('');
  const [amount, setAmount] = useState('');
  const [pricing, setPricing] = useState('fixed');
  const [terms, setTerms] = useState('50% upfront, 50% on completion');
  const [validDays, setValidDays] = useState('30');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = title.trim() && scope.trim().length >= 10 && Number(amount) >= 0 && amount !== '' &&
    (clientId || clientName.trim());

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch('/api/proposals/generate', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          clientId: clientId || undefined,
          clientName: clientId ? undefined : clientName.trim() || undefined,
          title: title.trim(),
          scopeDescription: scope.trim(),
          deliverablesRaw: deliverables.trim(),
          timelineDescription: timeline.trim(),
          totalAmount: Number(amount),
          pricingType: pricing,
          paymentTerms: terms.trim(),
          validDays: Number(validDays),
        }),
      });
      const json = (await res.json()) as Proposal & { detail?: string };
      if (!res.ok) {
        setError(typeof json.detail === 'string' ? json.detail : 'Could not generate proposal');
        setBusy(false);
        return;
      }
      router.push(`/butler/proposals/${json.id}`);
      router.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Could not generate proposal');
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link href="/butler/proposals" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft size={15} /> Back to proposals
      </Link>
      <div>
        <h1 className="text-2xl font-bold text-gray-900">New proposal</h1>
        <p className="mt-1 text-sm text-gray-500">Describe the work — Kora writes the full proposal with clause explanations.</p>
      </div>
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
              <input className={input} value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Acme Corp" />
            </div>
          )}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Proposal title <span className="text-red-400">*</span></label>
          <input className={input} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Q3 Campaign Landing Pages" />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Scope — what you&apos;ll do <span className="text-red-400">*</span></label>
          <textarea className={input} rows={3} value={scope} onChange={(e) => setScope(e.target.value)} placeholder="Describe the work in plain English." />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Deliverables</label>
          <textarea className={input} rows={2} value={deliverables} onChange={(e) => setDeliverables(e.target.value)} placeholder="One per line is fine." />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Timeline</label>
          <input className={input} value={timeline} onChange={(e) => setTimeline(e.target.value)} placeholder="4 weeks from kickoff, with weekly check-ins" />
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Total amount <span className="text-red-400">*</span></label>
            <input type="number" className={input} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="4000" />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Pricing</label>
            <select className={input} value={pricing} onChange={(e) => setPricing(e.target.value)}>
              {PRICING.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Valid for</label>
            <select className={input} value={validDays} onChange={(e) => setValidDays(e.target.value)}>
              {['14', '30', '60', '90'].map((d) => <option key={d} value={d}>{d} days</option>)}
            </select>
          </div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Payment terms</label>
          <input className={input} value={terms} onChange={(e) => setTerms(e.target.value)} />
        </div>
        {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        <div className="flex justify-end">
          <button onClick={generate} disabled={busy || !ready}
            className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-5 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60">
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
            {busy ? 'Writing your proposal…' : 'Generate proposal'}
          </button>
        </div>
      </Card>
    </div>
  );
}
