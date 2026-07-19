'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronDown, Download, Send, PenLine, Loader2, ScanSearch } from 'lucide-react';
import { Card, CardHeader, Badge } from '@/components/ui';
import { FormattedText } from '@/components/formatted-text';
import { formatDate, humanize } from '@/lib/utils';
import { authedFetch, downloadAuthed } from '@/lib/api/browser';
import type { Contract, ContractReview } from '@/lib/api/types';
import { ContractReviewView } from './contract-review';

export function ContractList({ contracts }: { contracts: Contract[] }) {
  const router = useRouter();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [reviewBusy, setReviewBusy] = useState<string | null>(null);
  const [reviews, setReviews] = useState<Record<string, ContractReview>>({});

  async function runReview(id: string) {
    setReviewBusy(id);
    setMsg(null);
    try {
      const res = await authedFetch(`/api/contracts/${id}/review`, { method: 'POST' });
      const json = await res.json();
      if (!res.ok) {
        setMsg(typeof json.detail === 'string' ? json.detail : 'Could not review this contract.');
        return;
      }
      setReviews((r) => ({ ...r, [id]: json as ContractReview }));
      setExpanded(id);
    } catch {
      setMsg('Could not reach the contract-review agent.');
    } finally {
      setReviewBusy(null);
    }
  }

  async function setStatus(id: string, status: string) {
    setPending(id);
    setMsg(null);
    try {
      await authedFetch(`/api/contracts/${id}/status`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      if (status === 'signed') {
        setMsg('Contract signed — Kora auto-created the matching invoices from its payment schedule.');
      }
      router.refresh();
    } finally {
      setPending(null);
    }
  }

  return (
    <Card>
      <CardHeader title="Contracts" subtitle="AI-generated, jurisdiction-aware agreements" />
      {msg && (
        <div className="border-b border-gray-100 bg-kora-50 px-5 py-2.5 text-xs text-kora-700">{msg}</div>
      )}
      <ul className="divide-y divide-gray-100">
        {contracts.map((c) => {
          const open = expanded === c.id;
          // Prefer a freshly-run review; else the one auto-generated at creation (terms._review).
          const review = reviews[c.id] ?? ((c.terms as any)?._review as ContractReview | undefined);
          return (
            <li key={c.id}>
              <div className="flex items-center justify-between px-5 py-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-900">{c.title ?? humanize(c.type)}</span>
                    <Badge value={c.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-gray-500">
                    {humanize(c.type)} · {c.clientName} · {c.jurisdiction} · {formatDate(c.createdAt)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {c.status === 'draft' && (
                    <button
                      onClick={() => setStatus(c.id, 'sent')}
                      disabled={pending === c.id}
                      className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      <Send size={12} /> Send
                    </button>
                  )}
                  {(c.status === 'draft' || c.status === 'sent') && (
                    <button
                      onClick={() => setStatus(c.id, 'signed')}
                      disabled={pending === c.id}
                      className="inline-flex items-center gap-1 rounded-md border border-emerald-200 px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
                    >
                      {pending === c.id ? <Loader2 size={12} className="animate-spin" /> : <PenLine size={12} />} Mark signed
                    </button>
                  )}
                  <button
                    onClick={() => runReview(c.id)}
                    disabled={reviewBusy === c.id}
                    className="inline-flex items-center gap-1 rounded-md border border-kora-200 px-2.5 py-1 text-xs font-medium text-kora-700 hover:bg-kora-50 disabled:opacity-60"
                    title="AI risk review — flag risky or missing clauses"
                  >
                    {reviewBusy === c.id ? <Loader2 size={12} className="animate-spin" /> : <ScanSearch size={12} />} Review
                  </button>
                  <button
                    onClick={() => downloadAuthed(`/api/contracts/${c.id}/pdf`, `${c.title ?? 'contract'}.pdf`)}
                    className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                  >
                    <Download size={12} /> PDF
                  </button>
                  <button
                    onClick={() => setExpanded(open ? null : c.id)}
                    className="rounded-md p-1 text-gray-400 hover:bg-gray-100"
                    aria-label="Toggle preview"
                  >
                    <ChevronDown size={16} className={open ? 'rotate-180 transition' : 'transition'} />
                  </button>
                </div>
              </div>

              {open && review && (
                <div className="border-t border-gray-100 bg-gray-50 px-5 py-4">
                  <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
                    <ScanSearch size={13} /> AI risk review
                  </p>
                  <ContractReviewView review={review} />
                </div>
              )}

              {open && (
                <div className="grid gap-4 bg-gray-50 px-5 py-4 lg:grid-cols-3">
                  <div className="kora-scroll col-span-2 max-h-96 overflow-auto rounded-lg border border-gray-200 bg-white p-4 text-xs leading-relaxed text-gray-700">
                    {c.contentMd ? <FormattedText text={c.contentMd} /> : '(no content)'}
                  </div>
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
                      Plain-English clauses
                    </p>
                    <ul className="space-y-2">
                      {Object.entries(c.sectionExplanations ?? {}).map(([k, v]) => (
                        <li key={k} className="rounded-lg border border-gray-200 bg-white p-2.5 text-xs">
                          <span className="font-semibold text-gray-900">§{k}</span>{' '}
                          <span className="text-gray-600">{v}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
