'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Loader2, Send, FileSignature, CheckCircle2 } from 'lucide-react';
import { Card, CardHeader, Badge } from '@/components/ui';
import { FormattedText } from '@/components/formatted-text';
import { authedFetch } from '@/lib/api/browser';
import { formatMoney } from '@/lib/utils';
import type { Proposal } from '@/lib/api/types';

export function ProposalDetail({ proposal }: { proposal: Proposal }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [status, setStatus] = useState(proposal.status);
  const [contractId, setContractId] = useState(proposal.contractId);

  async function act(kind: 'send' | 'accept') {
    setBusy(kind);
    setMsg(null);
    try {
      const res = await authedFetch(`/api/proposals/${proposal.id}/${kind}`, { method: 'POST' });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Action failed');
      if (kind === 'send') {
        setMsg('Queued for your approval in the Business Manager — Kora never sends to a client without your sign-off.');
      } else {
        setStatus('accepted');
        setContractId(json.contractId);
        setMsg('Accepted — Kora generated a matching contract (now in Contracts, auto-reviewed for risk).');
      }
      router.refresh();
    } catch (e: any) {
      setMsg(e?.message ?? 'Action failed');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <Link href="/butler/proposals" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft size={15} /> Back to proposals
      </Link>

      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-gray-900">{proposal.title}</h1>
              <Badge value={status} />
            </div>
            <p className="mt-1 text-xs text-gray-500">
              {proposal.proposalNumber} · {formatMoney(proposal.totalAmount, proposal.currency)} · {proposal.pricingType}
              {proposal.validUntil && ` · valid until ${proposal.validUntil}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => act('send')} disabled={busy !== null || status !== 'draft'}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
              {busy === 'send' ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Send to client
            </button>
            <button onClick={() => act('accept')} disabled={busy !== null || !!contractId}
              className="inline-flex items-center gap-1.5 rounded-lg bg-kora-600 px-3 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-50">
              {busy === 'accept' ? <Loader2 size={14} className="animate-spin" /> : <FileSignature size={14} />}
              {contractId ? 'Contract created' : 'Accept → contract'}
            </button>
          </div>
        </div>
      </Card>

      {msg && (
        <div className="flex items-start gap-2 rounded-lg bg-kora-50 px-4 py-3 text-sm text-kora-800">
          <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> {msg}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Proposal" subtitle="AI-generated — review before sending" />
          <div className="kora-scroll max-h-[34rem] overflow-auto p-5 text-sm leading-relaxed text-gray-700">
            {proposal.contentMd ? <FormattedText text={proposal.contentMd} /> : '(no content)'}
          </div>
        </Card>
        <Card>
          <CardHeader title="What each section means" />
          <ul className="space-y-2 p-4">
            {Object.entries(proposal.sectionExplanations ?? {}).map(([k, v]) => (
              <li key={k} className="rounded-lg border border-gray-200 bg-white p-2.5 text-xs">
                <span className="font-semibold text-gray-900">§{k}</span> <span className="text-gray-600">{v}</span>
              </li>
            ))}
            {Object.keys(proposal.sectionExplanations ?? {}).length === 0 && (
              <li className="text-sm text-gray-500">No explanations.</li>
            )}
          </ul>
        </Card>
      </div>
    </div>
  );
}
