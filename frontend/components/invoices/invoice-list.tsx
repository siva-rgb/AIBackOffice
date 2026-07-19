'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Mail, ChevronDown, Send, CheckCircle2, Loader2, Bot, Scale, Link2, Copy, Check, FileDown, DollarSign } from 'lucide-react';
import { Card, CardHeader, Badge } from '@/components/ui';
import { formatMoney, formatDate, formatDateTime, daysBetween } from '@/lib/utils';
import { authedFetch } from '@/lib/api/browser';

export interface FollowUpEmail {
  createdAt: string;
  attempt: number;
  subject: string;
  body: string;
}

export interface InvoiceVM {
  id: string;
  invoiceNumber: string;
  clientName: string;
  clientEmail: string;
  total: number;
  currency: string;
  status: string;
  dueDate: string;
  contractId: string | null;
  followUpCount: number;
  followUps: FollowUpEmail[];
  pdfPath?: string | null;
  emailMessageId?: string | null;
  sentAt?: string | null;
  paymentTerms?: string | null;
  amountPaid?: number;
}

export interface DemandResult {
  subject: string;
  body: string;
  contractGrounded: boolean;
  contractClause: string | null;
  daysOverdue: number;
}

export function InvoiceList({ invoices }: { invoices: InvoiceVM[] }) {
  const router = useRouter();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentMsg, setAgentMsg] = useState<string | null>(null);
  const [demandBusy, setDemandBusy] = useState<string | null>(null);
  const [demands, setDemands] = useState<Record<string, DemandResult>>({});
  const [demandError, setDemandError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [pdfBusy, setPdfBusy] = useState<string | null>(null);
  const [paymentOpen, setPaymentOpen] = useState<string | null>(null);
  const [paymentAmount, setPaymentAmount] = useState('');
  const [paymentBusy, setPaymentBusy] = useState<string | null>(null);

  async function act(id: string, fn: () => Promise<Response>) {
    setPending(id);
    try {
      await fn();
      router.refresh();
    } finally {
      setPending(null);
    }
  }

  async function generateDemand(id: string) {
    setDemandBusy(id);
    setDemandError(null);
    try {
      const res = await authedFetch(`/api/invoices/${id}/demand`, { method: 'POST' });
      const json = await res.json();
      if (!res.ok) {
        setDemandError(typeof json.detail === 'string' ? json.detail : 'Could not draft the demand letter.');
        return;
      }
      setDemands((d) => ({ ...d, [id]: json as DemandResult }));
      setExpanded(id);
    } catch {
      setDemandError('Could not reach the demand-letter agent.');
    } finally {
      setDemandBusy(null);
    }
  }

  async function copyDemand(id: string) {
    const d = demands[id];
    if (!d) return;
    await navigator.clipboard.writeText(`${d.subject}\n\n${d.body}`);
    setCopied(id);
    setTimeout(() => setCopied((c) => (c === id ? null : c)), 1500);
  }

  async function recordPayment(id: string) {
    const amount = parseFloat(paymentAmount);
    if (!amount || amount <= 0) return;
    setPaymentBusy(id);
    try {
      await authedFetch(`/api/invoices/${id}/payment`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ amount }),
      });
      setPaymentOpen(null);
      setPaymentAmount('');
      router.refresh();
    } finally {
      setPaymentBusy(null);
    }
  }

  async function downloadPdf(id: string, invoiceNumber: string) {
    setPdfBusy(id);
    try {
      const res = await authedFetch(`/api/invoices/${id}/pdf/download`);
      const json = await res.json();
      if (res.ok && json.url) {
        window.open(json.url, '_blank');
      } else {
        // Streaming fallback — download via Blob
        const blob = new Blob([JSON.stringify(json)], { type: 'application/pdf' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `invoice-${invoiceNumber}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      // silent
    } finally {
      setPdfBusy(null);
    }
  }

  async function runFollowUpAgent() {
    setAgentBusy(true);
    setAgentMsg(null);
    try {
      const res = await authedFetch('/api/invoices/follow-up', { method: 'POST' });
      const json = await res.json();
      setAgentMsg(
        json.sent > 0
          ? `Agent sent ${json.sent} follow-up email${json.sent > 1 ? 's' : ''} across ${json.scanned} open invoices.`
          : `Agent scanned ${json.scanned} open invoices — none are due for a follow-up right now.`,
      );
      router.refresh();
    } finally {
      setAgentBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Invoices"
        subtitle="Status updates as clients view and pay"
        action={
          <button
            onClick={runFollowUpAgent}
            disabled={agentBusy}
            className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
          >
            {agentBusy ? <Loader2 size={14} className="animate-spin" /> : <Bot size={14} />}
            Run follow-up agent
          </button>
        }
      />
      {agentMsg && (
        <div className="border-b border-gray-100 bg-kora-50 px-5 py-2.5 text-xs text-kora-700">
          {agentMsg}
        </div>
      )}
      {demandError && (
        <div className="border-b border-gray-100 bg-red-50 px-5 py-2.5 text-xs text-red-700">
          {demandError}
        </div>
      )}
      <ul className="divide-y divide-gray-100">
        {invoices.map((inv) => {
          const overdueDays = daysBetween(inv.dueDate);
          const isOpen = expanded === inv.id;
          return (
            <li key={inv.id}>
              <div className="flex items-center justify-between px-5 py-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-900">{inv.invoiceNumber}</span>
                    <Badge value={inv.status} />
                    {inv.followUpCount > 0 && (
                      <span className="inline-flex items-center gap-1 text-xs text-gray-400">
                        <Mail size={12} /> {inv.followUpCount} follow-up{inv.followUpCount > 1 ? 's' : ''}
                      </span>
                    )}
                    {inv.contractId && (
                      <span className="inline-flex items-center gap-1 text-xs text-fuchsia-500" title="Linked to a contract">
                        <Link2 size={12} /> contract
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-gray-500">
                    {inv.clientName} · due {formatDate(inv.dueDate)}
                    {inv.status === 'overdue' && overdueDays > 0 && (
                      <span className="text-red-600"> · {overdueDays} days overdue</span>
                    )}
                    {inv.amountPaid != null && inv.amountPaid > 0 && inv.status !== 'paid' && (
                      <span className="text-emerald-600"> · {formatMoney(inv.amountPaid, inv.currency)} paid</span>
                    )}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="tabular-nums text-sm font-semibold text-gray-900">
                    {formatMoney(inv.total, inv.currency)}
                  </span>
                  {inv.status === 'draft' && (
                    <button
                      onClick={() =>
                        act(inv.id, () => authedFetch(`/api/invoices/${inv.id}/send`, { method: 'POST' }))
                      }
                      disabled={pending === inv.id}
                      className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      {pending === inv.id ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />} Send
                    </button>
                  )}
                  <button
                    onClick={() => downloadPdf(inv.id, inv.invoiceNumber)}
                    disabled={pdfBusy === inv.id}
                    className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
                    title="Download PDF"
                  >
                    {pdfBusy === inv.id ? <Loader2 size={12} className="animate-spin" /> : <FileDown size={12} />} PDF
                  </button>
                  {inv.emailMessageId && (
                    <span className="inline-flex items-center gap-1 text-xs text-emerald-600" title="Delivered via email">
                      <Mail size={12} /> Delivered
                    </span>
                  )}
                  {(inv.status === 'sent' || inv.status === 'overdue' || inv.status === 'viewed') && (
                    <button
                      onClick={() =>
                        act(inv.id, () =>
                          authedFetch(`/api/invoices/${inv.id}`, {
                            method: 'PATCH',
                            headers: { 'content-type': 'application/json' },
                            body: JSON.stringify({ status: 'paid' }),
                          }),
                        )
                      }
                      disabled={pending === inv.id}
                      className="inline-flex items-center gap-1 rounded-md border border-emerald-200 px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
                    >
                      <CheckCircle2 size={12} /> Mark paid
                    </button>
                  )}
                  {(inv.status === 'sent' || inv.status === 'overdue' || inv.status === 'viewed') && (
                    <button
                      onClick={() => { setPaymentOpen(paymentOpen === inv.id ? null : inv.id); setPaymentAmount(''); }}
                      className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
                      title="Record a partial or full payment"
                    >
                      <DollarSign size={12} /> Record payment
                    </button>
                  )}
                  {inv.status === 'overdue' && (
                    <button
                      onClick={() => generateDemand(inv.id)}
                      disabled={demandBusy === inv.id}
                      className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
                      title="Draft a formal payment demand, grounded in the linked contract"
                    >
                      {demandBusy === inv.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Scale size={12} />
                      )}
                      Demand letter
                    </button>
                  )}
                  {(inv.followUps.length > 0 || demands[inv.id]) && (
                    <button
                      onClick={() => setExpanded(isOpen ? null : inv.id)}
                      className="rounded-md p-1 text-gray-400 hover:bg-gray-100"
                      aria-label="Toggle details"
                    >
                      <ChevronDown size={16} className={isOpen ? 'rotate-180 transition' : 'transition'} />
                    </button>
                  )}
                </div>
              </div>

              {paymentOpen === inv.id && (
                <div className="border-t border-gray-100 bg-gray-50 px-5 py-3">
                  <p className="mb-2 text-xs font-medium text-gray-600">
                    Record payment
                    {inv.amountPaid && inv.amountPaid > 0
                      ? ` · ${formatMoney(inv.amountPaid, inv.currency)} already paid, ${formatMoney(inv.total - inv.amountPaid, inv.currency)} remaining`
                      : ''}
                  </p>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min="0.01"
                      step="0.01"
                      placeholder="Amount received"
                      value={paymentAmount}
                      onChange={(e) => setPaymentAmount(e.target.value)}
                      className="w-40 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500"
                    />
                    <button
                      onClick={() => recordPayment(inv.id)}
                      disabled={!paymentAmount || paymentBusy === inv.id}
                      className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
                    >
                      {paymentBusy === inv.id ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                      Save
                    </button>
                    <button onClick={() => setPaymentOpen(null)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
                  </div>
                </div>
              )}

              {isOpen && (inv.followUps.length > 0 || demands[inv.id]) && (
                <div className="space-y-3 bg-gray-50 px-5 py-4">
                  {demands[inv.id] && (
                    <div className="rounded-lg border border-red-200 bg-white p-4">
                      <div className="flex items-center justify-between">
                        <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-red-600">
                          <Scale size={13} /> Payment demand letter
                        </span>
                        <button
                          onClick={() => copyDemand(inv.id)}
                          className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
                        >
                          {copied === inv.id ? <Check size={12} /> : <Copy size={12} />}
                          {copied === inv.id ? 'Copied' : 'Copy'}
                        </button>
                      </div>
                      {demands[inv.id].contractGrounded ? (
                        <div className="mt-2 rounded-md bg-fuchsia-50 px-3 py-2 text-xs text-fuchsia-800">
                          <span className="inline-flex items-center gap-1 font-semibold">
                            <Link2 size={12} /> Grounded in the linked contract
                          </span>
                          {demands[inv.id].contractClause && (
                            <p className="mt-1 italic text-fuchsia-700">
                              “{demands[inv.id].contractClause}”
                            </p>
                          )}
                        </div>
                      ) : (
                        <p className="mt-2 text-xs text-gray-400">
                          No contract linked — drafted from the invoice details only.
                        </p>
                      )}
                      <p className="mt-2 text-sm font-medium text-gray-800">{demands[inv.id].subject}</p>
                      <pre className="mt-1.5 whitespace-pre-wrap font-sans text-xs leading-relaxed text-gray-600">
                        {demands[inv.id].body}
                      </pre>
                    </div>
                  )}
                  {inv.followUps.length > 0 && (
                  <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                    AI follow-up history
                  </p>
                  )}
                  {inv.followUps.map((f, i) => (
                    <div key={i} className="rounded-lg border border-gray-200 bg-white p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-gray-900">
                          Attempt {f.attempt}:{' '}
                          {['', 'Gentle reminder', 'Firm follow-up', 'Final notice'][f.attempt]}
                        </span>
                        <span className="text-xs text-gray-400">{formatDateTime(f.createdAt)}</span>
                      </div>
                      <p className="mt-1 text-sm font-medium text-gray-800">{f.subject}</p>
                      <pre className="mt-1.5 whitespace-pre-wrap font-sans text-xs leading-relaxed text-gray-600">
                        {f.body}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
