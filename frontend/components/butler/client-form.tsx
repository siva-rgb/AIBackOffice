'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Loader2, UserPlus } from 'lucide-react';
import { Card } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import { cn } from '@/lib/utils';

const input =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';

const TYPES = ['individual', 'company', 'agency', 'marketplace'];
const INDUSTRIES = ['Design', 'Development', 'Writing', 'Marketing', 'Consulting', 'E-commerce', 'Other'];

export function ClientForm() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [contactEmailsRaw, setContactEmailsRaw] = useState('');
  const [company, setCompany] = useState('');
  const [clientType, setClientType] = useState('individual');
  const [whatWeDo, setWhatWeDo] = useState('');
  const [industry, setIndustry] = useState('');
  const [billingAddress, setBillingAddress] = useState('');
  const [taxId, setTaxId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    const contactEmails = contactEmailsRaw
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => e.includes('@'));
    try {
      const res = await authedFetch('/api/clients', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim() || undefined,
          contactEmails: contactEmails.length ? contactEmails : undefined,
          company: company.trim() || undefined,
          clientType,
          whatWeDo: whatWeDo.trim() || undefined,
          industry: industry || undefined,
          billingAddress: billingAddress.trim() || undefined,
          taxId: taxId.trim() || undefined,
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        setError(typeof json.detail === 'string' ? json.detail : 'Could not create client');
        setBusy(false);
        return;
      }
      router.push(`/butler/clients/${json.id}`);
      router.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Could not create client');
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link href="/butler" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft size={15} /> Back to Butler
      </Link>
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Add a client</h1>
        <p className="mt-1 text-sm text-gray-500">A thin profile is enough — Kora fills in the rest from your invoices and notes.</p>
      </div>
      <Card className="space-y-4 p-5">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Client name <span className="text-red-400">*</span></label>
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Corp" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Email</label>
            <input type="email" className={input} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ap@acme.com" />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Company</label>
            <input className={input} value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Acme Corp" />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Additional contacts <span className="font-normal text-gray-400">(optional)</span>
          </label>
          <input
            className={input}
            value={contactEmailsRaw}
            onChange={(e) => setContactEmailsRaw(e.target.value)}
            placeholder="cfo@acme.com, pm@acme.com"
          />
          <p className="mt-1 text-xs text-gray-400">
            Extra addresses for this client (comma-separated). Kora also tracks email from anyone at the
            client’s work domain automatically.
          </p>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Type</label>
          <div className="flex flex-wrap gap-2">
            {TYPES.map((t) => (
              <button key={t} onClick={() => setClientType(t)}
                className={cn('rounded-lg border px-3 py-1.5 text-sm font-medium capitalize',
                  clientType === t ? 'border-kora-500 bg-kora-50 text-kora-700' : 'border-gray-200 text-gray-600 hover:border-kora-300')}>
                {t}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">What do you do for them?</label>
          <input className={input} value={whatWeDo} onChange={(e) => setWhatWeDo(e.target.value)} placeholder="We build and maintain their Shopify store" />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Industry</label>
          <select className={input} value={industry} onChange={(e) => setIndustry(e.target.value)}>
            <option value="">Select…</option>
            {INDUSTRIES.map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Billing address <span className="font-normal text-gray-400">(optional — pre-fills invoices)</span></label>
          <textarea className={input} rows={2} value={billingAddress} onChange={(e) => setBillingAddress(e.target.value)} placeholder={"123 Main St\nCity, State 10001"} />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Tax ID / VAT number <span className="font-normal text-gray-400">(optional)</span></label>
          <input className={input} value={taxId} onChange={(e) => setTaxId(e.target.value)} placeholder="VAT / GST / EIN" />
        </div>
        {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        <div className="flex justify-end">
          <button onClick={save} disabled={busy || !name.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-5 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60">
            {busy ? <Loader2 size={15} className="animate-spin" /> : <UserPlus size={15} />} Add client
          </button>
        </div>
      </Card>
    </div>
  );
}
