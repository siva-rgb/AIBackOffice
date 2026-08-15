import Link from 'next/link';
import { Plus, FileText } from 'lucide-react';
import { serverGet } from '@/lib/api/server';
import type { Invoice, AgentLog } from '@/lib/api/types';
import { InvoiceList, type InvoiceVM } from '@/components/invoices/invoice-list';
import { Card } from '@/components/ui';
import { BackendDown } from '@/components/backend-down';

export const dynamic = 'force-dynamic';

export default async function InvoicesPage() {
  let invoices: Invoice[];
  let logs: AgentLog[];
  try {
    [invoices, logs] = await Promise.all([
      serverGet<Invoice[]>('/api/invoices'),
      serverGet<AgentLog[]>('/api/agents/log'),
    ]);
  } catch {
    return <BackendDown />;
  }

  const followUpsByInvoice = new Map<string, InvoiceVM['followUps']>();
  for (const l of logs) {
    if (l.agentType !== 'invoice_follow_up' || !l.sourceRecordId) continue;
    const out = l.output as { subject?: string; body?: string } | null;
    const input = l.input as { attempt?: number } | null;
    const list = followUpsByInvoice.get(l.sourceRecordId) ?? [];
    list.push({
      createdAt: l.createdAt,
      attempt: input?.attempt ?? list.length + 1,
      subject: out?.subject ?? l.action,
      body: out?.body ?? '(email body not recorded)',
    });
    followUpsByInvoice.set(l.sourceRecordId, list);
  }

  const vms: InvoiceVM[] = invoices.map((i) => ({
    id: i.id,
    invoiceNumber: i.invoiceNumber,
    clientName: i.clientName,
    clientEmail: i.clientEmail,
    total: i.total,
    currency: i.currency,
    status: i.status,
    dueDate: i.dueDate,
    contractId: i.contractId ?? null,
    followUpCount: i.followUpCount,
    followUps: (followUpsByInvoice.get(i.id) ?? []).sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
    pdfPath: i.pdfPath ?? null,
    emailMessageId: i.emailMessageId ?? null,
    sentAt: i.sentAt ?? null,
    paymentTerms: i.paymentTerms ?? null,
    amountPaid: i.amountPaid ?? 0,
    paymentLink: i.paymentLink ?? null,
  }));

  return (
    <div className="space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Invoices</h1>
          <p className="mt-1 text-sm text-gray-500">
            Send invoices and let the AI agent chase overdue payments automatically.
          </p>
        </div>
        <Link
          href="/invoices/new"
          className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700"
        >
          <Plus size={16} /> New invoice
        </Link>
      </header>

      {vms.length === 0 ? (
        <Card className="flex flex-col items-center justify-center py-16 text-center">
          <FileText className="text-kora-600" size={32} />
          <h2 className="mt-4 text-lg font-semibold text-gray-900">Create your first invoice</h2>
          <p className="mt-1 max-w-sm text-sm text-gray-500">
            Send professional invoices in seconds. Kora will follow up automatically if unpaid.
          </p>
          <Link
            href="/invoices/new"
            className="mt-6 inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700"
          >
            <Plus size={16} /> Create invoice
          </Link>
        </Card>
      ) : (
        <InvoiceList invoices={vms} />
      )}
    </div>
  );
}
