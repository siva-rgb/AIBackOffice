'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, Sparkles } from 'lucide-react';
import { authedFetch } from '@/lib/api/browser';

const TYPES = [
  { value: 'nda', label: 'NDA', hint: 'Mutual or one-way non-disclosure' },
  { value: 'freelance_agreement', label: 'Freelance Agreement', hint: 'SOW + payment terms' },
  { value: 'service_contract', label: 'Service Contract', hint: 'Ongoing retainer / project' },
  { value: 'refund_policy', label: 'Refund Policy', hint: 'E-commerce or services' },
  { value: 'ip_transfer', label: 'IP Transfer', hint: 'Work-for-hire assignment' },
];

type Field = {
  key: string;
  label: string;
  control?: 'text' | 'textarea' | 'number' | 'date' | 'select';
  placeholder?: string;
  options?: string[];
  optional?: boolean;
};

// Per-type structured inputs → become well-named keys in `terms` for the LLM.
const FIELDS: Record<string, Field[]> = {
  freelance_agreement: [
    { key: 'project_description', label: 'Project description', control: 'textarea', placeholder: 'Website redesign and brand refresh' },
    { key: 'deliverables', label: 'Deliverables', control: 'textarea', placeholder: 'Homepage, 5 inner pages, style guide', optional: true },
    { key: 'start_date', label: 'Start date', control: 'date', optional: true },
    { key: 'deadline', label: 'Completion deadline', control: 'date', optional: true },
    { key: 'fee_type', label: 'Fee type', control: 'select', options: ['fixed', 'hourly'] },
    { key: 'amount', label: 'Amount (total fee or hourly rate)', placeholder: '$4,000' },
    { key: 'payment_schedule', label: 'Payment schedule', control: 'select', options: ['50% upfront, 50% on delivery', 'milestone-based', 'on completion', 'custom'] },
    { key: 'payment_terms_days', label: 'Payment terms (Net days)', control: 'number', placeholder: '14', optional: true },
    { key: 'revision_rounds', label: 'Revision rounds included', control: 'number', placeholder: '2', optional: true },
    { key: 'ip_ownership', label: 'IP ownership', control: 'select', options: ['transfers to client on full payment', 'freelancer retains a license'] },
  ],
  nda: [
    { key: 'mutual', label: 'Type', control: 'select', options: ['mutual', 'one-way'] },
    { key: 'confidential_information', label: 'What the confidential information covers', control: 'textarea', placeholder: 'Product designs, financials, customer data' },
    { key: 'purpose', label: 'Purpose of disclosure', control: 'textarea', placeholder: 'Evaluating a potential partnership', optional: true },
    { key: 'duration', label: 'Term / duration', placeholder: '3 years from signing' },
  ],
  service_contract: [
    { key: 'services', label: 'Services provided', control: 'textarea', placeholder: 'Monthly social-media management and reporting' },
    { key: 'term', label: 'Term / duration', placeholder: '12 months' },
    { key: 'fee', label: 'Fee', placeholder: '$1,500 / month' },
    { key: 'billing_frequency', label: 'Billing frequency', control: 'select', options: ['monthly', 'quarterly', 'annually', 'per project'] },
    { key: 'payment_terms_days', label: 'Payment terms (Net days)', control: 'number', placeholder: '14', optional: true },
    { key: 'auto_renew', label: 'Auto-renew at end of term?', control: 'select', options: ['no', 'yes'] },
  ],
  refund_policy: [
    { key: 'business_type', label: 'Business / product type', placeholder: 'Digital design templates' },
    { key: 'refund_window_days', label: 'Refund window (days)', control: 'number', placeholder: '14' },
    { key: 'eligible_conditions', label: 'When refunds are allowed', control: 'textarea', placeholder: 'Unused, within window, with proof of purchase' },
    { key: 'non_refundable', label: 'Non-refundable items', control: 'textarea', placeholder: 'Custom work, downloaded files', optional: true },
    { key: 'refund_method', label: 'Refund method & timeframe', placeholder: 'Original payment method, within 7 business days' },
  ],
  ip_transfer: [
    { key: 'work_description', label: 'Work being assigned', control: 'textarea', placeholder: 'Logo and brand identity assets' },
    { key: 'consideration', label: 'Consideration (payment)', placeholder: '$2,500' },
    { key: 'effective_date', label: 'Effective date', control: 'date', optional: true },
    { key: 'moral_rights_waiver', label: 'Include a moral-rights waiver?', control: 'select', options: ['yes', 'no'] },
  ],
};

const input =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function ContractWizard() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [type, setType] = useState('freelance_agreement');
  const [clientName, setClientName] = useState('');
  const [clientEmail, setClientEmail] = useState('');
  const [providerName, setProviderName] = useState('');
  const [jurisdiction, setJurisdiction] = useState('US');
  const [values, setValues] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fields = FIELDS[type] ?? [];
  const primary = fields.find((f) => !f.optional && f.control !== 'select');
  const setVal = (k: string, v: string) => setValues((s) => ({ ...s, [k]: v }));
  const valOf = (f: Field) =>
    values[f.key] ?? (f.control === 'select' && f.options?.length ? f.options[0] : '');

  async function generate() {
    setBusy(true);
    setError(null);
    const termsObj: Record<string, string> = {};
    for (const f of fields) {
      const v = valOf(f);
      if (v && String(v).trim()) termsObj[f.key] = String(v).trim();
    }
    if (notes.trim()) termsObj['additional_notes'] = notes.trim();

    try {
      const res = await authedFetch('/api/contracts/generate', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          type,
          clientName,
          clientEmail: clientEmail || undefined,
          providerName: providerName || undefined,
          jurisdiction,
          terms: termsObj,
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        setError(typeof json.detail === 'string' ? json.detail : 'Could not generate contract');
        setBusy(false);
        return;
      }
      router.push('/contracts');
      router.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Could not generate contract');
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {step === 1 && (
        <div>
          <h2 className="mb-3 text-sm font-semibold text-gray-900">Step 1 · Choose a contract type</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {TYPES.map((t) => (
              <button
                key={t.value}
                onClick={() => { setType(t.value); setValues({}); }}
                className={`rounded-xl border p-4 text-left transition-colors ${
                  type === t.value ? 'border-kora-500 bg-kora-50' : 'border-gray-200 hover:border-kora-300'
                }`}
              >
                <p className="text-sm font-semibold text-gray-900">{t.label}</p>
                <p className="mt-0.5 text-xs text-gray-500">{t.hint}</p>
              </button>
            ))}
          </div>
          <div className="mt-6 flex justify-end">
            <button onClick={() => setStep(2)} className="rounded-lg bg-kora-600 px-5 py-2 text-sm font-semibold text-white hover:bg-kora-700">
              Next
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-900">Step 2 · Parties &amp; jurisdiction</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Your business name</label>
              <input className={input} value={providerName} onChange={(e) => setProviderName(e.target.value)} placeholder="Rivera Studio" />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Client name</label>
              <input className={input} value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Acme Corp" />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Client email (optional)</label>
              <input type="email" className={input} value={clientEmail} onChange={(e) => setClientEmail(e.target.value)} placeholder="legal@acme.com" />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Jurisdiction</label>
              <input className={input} value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} placeholder="US-CA" />
            </div>
          </div>
          <div className="flex justify-between">
            <button onClick={() => setStep(1)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Back</button>
            <button onClick={() => setStep(3)} disabled={!clientName} className="rounded-lg bg-kora-600 px-5 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-50">Next</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-900">Step 3 · Deal terms</h2>
          <p className="text-xs text-gray-500">
            Fill in what you know — Kora drafts the full {TYPES.find((t) => t.value === type)?.label} with the right
            protective clauses, then auto-reviews it for risks.
          </p>

          <div className="grid gap-4 sm:grid-cols-2">
            {fields.map((f) => {
              const wide = f.control === 'textarea';
              return (
                <div key={f.key} className={wide ? 'sm:col-span-2' : ''}>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    {f.label}{!f.optional && <span className="text-red-400"> *</span>}
                  </label>
                  {f.control === 'textarea' ? (
                    <textarea className={input} rows={2} value={values[f.key] ?? ''} onChange={(e) => setVal(f.key, e.target.value)} placeholder={f.placeholder} />
                  ) : f.control === 'select' ? (
                    <select className={input} value={valOf(f)} onChange={(e) => setVal(f.key, e.target.value)}>
                      {f.options!.map((o) => <option key={o} value={o}>{cap(o)}</option>)}
                    </select>
                  ) : (
                    <input
                      className={input}
                      type={f.control === 'number' ? 'number' : f.control === 'date' ? 'date' : 'text'}
                      value={values[f.key] ?? ''}
                      onChange={(e) => setVal(f.key, e.target.value)}
                      placeholder={f.placeholder}
                    />
                  )}
                </div>
              );
            })}
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Anything else? (optional)</label>
            <textarea className={input} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Any extra clauses or context you want included." />
          </div>

          {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
          <div className="flex justify-between">
            <button onClick={() => setStep(2)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Back</button>
            <button
              onClick={generate}
              disabled={busy || (primary ? !values[primary.key]?.trim() : false)}
              className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-5 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              {busy ? 'Generating & reviewing…' : 'Generate contract'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
