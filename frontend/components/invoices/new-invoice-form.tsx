'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Plus, Trash2, Loader2 } from 'lucide-react';
import { formatMoney } from '@/lib/utils';
import { authedFetch } from '@/lib/api/browser';
import type { Client } from '@/lib/api/types';

interface Item {
  description: string;
  quantity: number;
  rate: number;
}

const PAYMENT_TERMS = ['Due on receipt', 'Net 7', 'Net 14', 'Net 21', 'Net 30', 'Net 45', 'Net 60'];
const PAYMENT_TERMS_DAYS: Record<string, number> = {
  'Due on receipt': 0, 'Net 7': 7, 'Net 14': 14, 'Net 21': 21,
  'Net 30': 30, 'Net 45': 45, 'Net 60': 60,
};

function computeDueDate(invoiceDate: string, paymentTerms: string): string {
  const days = PAYMENT_TERMS_DAYS[paymentTerms] ?? 14;
  const d = new Date(invoiceDate);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export function NewInvoiceForm() {
  const router = useRouter();
  const today = new Date().toISOString().slice(0, 10);
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState('');
  const [clientName, setClientName] = useState('');
  const [clientEmail, setClientEmail] = useState('');
  const [invoiceDate, setInvoiceDate] = useState(today);
  const [paymentTerms, setPaymentTerms] = useState('Net 14');
  const [dueDate, setDueDate] = useState(() => computeDueDate(today, 'Net 14'));
  const [clientAddress, setClientAddress] = useState('');
  const [poNumber, setPoNumber] = useState('');
  const [clientTaxId, setClientTaxId] = useState('');
  const [taxRate, setTaxRate] = useState(0);
  const [notes, setNotes] = useState('');
  const [items, setItems] = useState<Item[]>([{ description: '', quantity: 1, rate: 0 }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    authedFetch('/api/clients').then((r) => r.json()).then((data) => {
      if (Array.isArray(data)) setClients(data);
    }).catch(() => {});
  }, []);

  function selectClient(id: string) {
    setSelectedClientId(id);
    if (!id) return;
    const c = clients.find((cl) => cl.id === id);
    if (!c) return;
    setClientName(c.name);
    if (c.email) setClientEmail(c.email);
    if (c.billingAddress) setClientAddress(c.billingAddress);
    if (c.taxId) setClientTaxId(c.taxId);
  }

  function handlePaymentTermsChange(terms: string) {
    setPaymentTerms(terms);
    setDueDate(computeDueDate(invoiceDate, terms));
  }

  function handleInvoiceDateChange(date: string) {
    setInvoiceDate(date);
    setDueDate(computeDueDate(date, paymentTerms));
  }

  const subtotal = items.reduce((s, i) => s + i.quantity * i.rate, 0);
  const taxAmount = (subtotal * taxRate) / 100;
  const total = subtotal + taxAmount;

  function updateItem(idx: number, patch: Partial<Item>) {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch('/api/invoices', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          clientId: selectedClientId || undefined,
          clientName,
          clientEmail,
          invoiceDate,
          paymentTerms,
          paymentTermsDays: PAYMENT_TERMS_DAYS[paymentTerms] ?? 14,
          dueDate,
          clientAddress: clientAddress || undefined,
          clientTaxId: clientTaxId || undefined,
          poNumber: poNumber || undefined,
          taxRate,
          currency: 'USD',
          notes: notes || undefined,
          lineItems: items.map((i) => ({
            description: i.description,
            quantity: Number(i.quantity),
            rate: Number(i.rate),
          })),
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        const msg = typeof json.detail === 'string' ? json.detail : json.error;
        setError(msg ?? 'Could not create invoice — check the fields and try again.');
        setBusy(false);
        return;
      }
      router.push('/invoices');
      router.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Could not create invoice');
      setBusy(false);
    }
  }

  const inputClass =
    'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';

  return (
    <form onSubmit={submit} className="space-y-6">
      {clients.length > 0 && (
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Pick a saved client <span className="font-normal text-gray-400">(pre-fills details)</span>
          </label>
          <select
            className={inputClass}
            value={selectedClientId}
            onChange={(e) => selectClient(e.target.value)}
          >
            <option value="">— Enter manually —</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}{c.company && c.company !== c.name ? ` (${c.company})` : ''}</option>
            ))}
          </select>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Client name</label>
          <input className={inputClass} value={clientName} onChange={(e) => setClientName(e.target.value)} required placeholder="Acme Corp" />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Client email</label>
          <input type="email" className={inputClass} value={clientEmail} onChange={(e) => setClientEmail(e.target.value)} required placeholder="billing@acme.com" />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Invoice date</label>
          <input type="date" className={inputClass} value={invoiceDate} onChange={(e) => handleInvoiceDateChange(e.target.value)} required />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Payment terms</label>
          <select className={inputClass} value={paymentTerms} onChange={(e) => handlePaymentTermsChange(e.target.value)}>
            {PAYMENT_TERMS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Due date</label>
          <input type="date" className={inputClass} value={dueDate} onChange={(e) => setDueDate(e.target.value)} required />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Tax rate (%)</label>
          <input type="number" min={0} max={100} step="0.1" className={inputClass} value={taxRate} onChange={(e) => setTaxRate(Number(e.target.value))} />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">PO / Reference number <span className="font-normal text-gray-400">(optional)</span></label>
          <input className={inputClass} value={poNumber} onChange={(e) => setPoNumber(e.target.value)} placeholder="PO-1234" />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Client tax ID <span className="font-normal text-gray-400">(optional)</span></label>
          <input className={inputClass} value={clientTaxId} onChange={(e) => setClientTaxId(e.target.value)} placeholder="VAT / GST / EIN" />
        </div>
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">Client billing address <span className="font-normal text-gray-400">(optional)</span></label>
        <textarea className={inputClass} rows={2} value={clientAddress} onChange={(e) => setClientAddress(e.target.value)} placeholder="123 Main St, City, Country" />
      </div>

      <div>
        <label className="mb-2 block text-sm font-medium text-gray-700">Line items</label>
        <div className="space-y-2">
          {items.map((it, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <input
                className={inputClass + ' flex-1'}
                placeholder="Description"
                value={it.description}
                onChange={(e) => updateItem(idx, { description: e.target.value })}
                required
              />
              <input
                type="number"
                min={1}
                className={inputClass + ' w-20'}
                placeholder="Qty"
                value={it.quantity}
                onChange={(e) => updateItem(idx, { quantity: Number(e.target.value) })}
              />
              <input
                type="number"
                min={0}
                step="0.01"
                className={inputClass + ' w-28'}
                placeholder="Rate"
                value={it.rate}
                onChange={(e) => updateItem(idx, { rate: Number(e.target.value) })}
              />
              <span className="w-24 text-right text-sm tabular-nums text-gray-700">
                {formatMoney(it.quantity * it.rate)}
              </span>
              {items.length > 1 && (
                <button
                  type="button"
                  onClick={() => setItems((prev) => prev.filter((_, i) => i !== idx))}
                  className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-red-600"
                >
                  <Trash2 size={15} />
                </button>
              )}
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setItems((prev) => [...prev, { description: '', quantity: 1, rate: 0 }])}
          className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-kora-600"
        >
          <Plus size={14} /> Add line item
        </button>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">Notes (optional)</label>
        <textarea className={inputClass} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>

      <div className="flex items-center justify-between border-t border-gray-100 pt-4">
        <div className="text-sm text-gray-500">
          Subtotal {formatMoney(subtotal)} · Tax {formatMoney(taxAmount)}
        </div>
        <div className="text-lg font-bold text-gray-900">Total {formatMoney(total)}</div>
      </div>

      {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div className="flex justify-end gap-3">
        <button
          type="button"
          onClick={() => router.push('/invoices')}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-5 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
        >
          {busy && <Loader2 size={15} className="animate-spin" />} Create invoice
        </button>
      </div>
    </form>
  );
}
