'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Sparkles,
  User2,
  Building2,
  Store,
  Users2,
  Rocket,
  UploadCloud,
  Loader2,
  Check,
  X,
  Plus,
  ArrowRight,
  ArrowLeft,
  BookOpen,
  FileText,
  Bell,
  FileSignature,
} from 'lucide-react';
import { authedFetch } from '@/lib/api/browser';
import { getSupabaseBrowser } from '@/lib/supabase/client';
import { cn } from '@/lib/utils';

const TOTAL = 5;

const BUSINESS_TYPES = [
  { id: 'freelancer', label: 'Freelancer', sub: 'Designer, developer, writer, consultant', icon: User2 },
  { id: 'online_seller', label: 'Online seller', sub: 'Etsy, marketplace or e-commerce', icon: Store },
  { id: 'small_business', label: 'Small business', sub: '1–5 person team', icon: Building2 },
  { id: 'agency', label: 'Agency', sub: 'A team serving multiple clients', icon: Users2 },
  { id: 'startup', label: 'Startup', sub: 'Building & scaling a product', icon: Rocket },
];

const COUNTRIES = [
  ['US', 'United States'], ['GB', 'United Kingdom'], ['CA', 'Canada'], ['AU', 'Australia'],
  ['IN', 'India'], ['DE', 'Germany'], ['FR', 'France'], ['NL', 'Netherlands'],
  ['SG', 'Singapore'], ['AE', 'United Arab Emirates'],
];
const CURRENCIES = ['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'INR', 'SGD', 'AED'];

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';

interface Client {
  name: string;
  email: string;
}

export function OnboardingWizard() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1
  const [businessType, setBusinessType] = useState<string>('freelancer');
  // Step 2
  const [fullName, setFullName] = useState('');
  const [businessName, setBusinessName] = useState('');
  const [country, setCountry] = useState('US');
  const [currency, setCurrency] = useState('USD');
  // Step 3
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadCount, setUploadCount] = useState<number | null>(null);
  // Step 4
  const [clients, setClients] = useState<Client[]>([]);
  const [clientName, setClientName] = useState('');
  const [clientEmail, setClientEmail] = useState('');

  // Prefill name from the signed-in user's metadata.
  useEffect(() => {
    (async () => {
      const supabase = getSupabaseBrowser();
      const { data } = await supabase.auth.getUser();
      const meta = data.user?.user_metadata as Record<string, string> | undefined;
      if (meta?.full_name) setFullName(meta.full_name);
    })();
  }, []);

  async function saveProfile() {
    // Persist the step-2 core identity (users columns)…
    const res = await authedFetch('/api/me', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fullName, businessName, country, currency }),
    });
    if (!res.ok) throw new Error('Could not save your profile. Please try again.');
    // …and the chosen business type into the business profile (best-effort —
    // don't block onboarding if the profile column isn't migrated yet).
    try {
      await authedFetch('/api/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ businessType }),
      });
    } catch {
      /* non-fatal */
    }
  }

  async function next() {
    setError(null);
    if (step === 2) {
      if (!fullName.trim()) {
        setError('Please enter your name.');
        return;
      }
      setSaving(true);
      try {
        await saveProfile();
      } catch (e: any) {
        setError(e?.message ?? 'Save failed');
        setSaving(false);
        return;
      }
      setSaving(false);
    }
    setStep((s) => Math.min(TOTAL, s + 1));
  }

  function back() {
    setError(null);
    setStep((s) => Math.max(1, s - 1));
  }

  async function uploadCsv(file: File) {
    setUploadBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await authedFetch('/api/bookkeeping/upload', { method: 'POST', body: fd });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? 'Upload failed');
      setUploadCount(json.inserted ?? 0);
    } catch (e: any) {
      setError(e?.message ?? 'Upload failed');
    } finally {
      setUploadBusy(false);
    }
  }

  function addClient() {
    if (!clientName.trim()) return;
    setClients((c) => [...c, { name: clientName.trim(), email: clientEmail.trim() }]);
    setClientName('');
    setClientEmail('');
  }

  async function finish() {
    setSaving(true);
    setError(null);
    try {
      const res = await authedFetch('/api/me', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ onboardingCompleted: true }),
      });
      if (!res.ok) throw new Error('Could not complete setup. Please try again.');
      router.replace('/dashboard');
      router.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Failed to finish');
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-2xl items-center gap-2 px-6 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-kora-600 text-white">
            <Sparkles size={18} />
          </div>
          <span className="text-lg font-bold">Kora</span>
          <span className="ml-auto text-xs font-medium text-gray-400">
            Step {step} of {TOTAL}
          </span>
        </div>
        <div className="h-1 w-full bg-gray-100">
          <div
            className="h-1 bg-kora-600 transition-all duration-300"
            style={{ width: `${(step / TOTAL) * 100}%` }}
          />
        </div>
      </header>

      <main className="mx-auto max-w-2xl px-6 py-10">
        {/* Step 1 — business type */}
        {step === 1 && (
          <Section
            title="What kind of business is this?"
            sub="We'll tailor your workspace and the AI's suggestions to fit."
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {BUSINESS_TYPES.map(({ id, label, sub, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setBusinessType(id)}
                  className={cn(
                    'flex items-start gap-3 rounded-xl border p-4 text-left transition-colors',
                    businessType === id
                      ? 'border-kora-500 bg-kora-50 ring-1 ring-kora-500'
                      : 'border-gray-200 bg-white hover:border-kora-300',
                  )}
                >
                  <Icon size={20} className="mt-0.5 shrink-0 text-kora-600" />
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{label}</p>
                    <p className="mt-0.5 text-xs text-gray-500">{sub}</p>
                  </div>
                </button>
              ))}
            </div>
          </Section>
        )}

        {/* Step 2 — profile */}
        {step === 2 && (
          <Section title="Tell us about you" sub="This appears on your invoices and contracts.">
            <div className="space-y-3">
              <Field label="Your name">
                <input className={inputCls} value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Alex Rivera" />
              </Field>
              <Field label="Business name">
                <input className={inputCls} value={businessName} onChange={(e) => setBusinessName(e.target.value)} placeholder="Rivera Studio" />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Country">
                  <select className={inputCls} value={country} onChange={(e) => setCountry(e.target.value)}>
                    {COUNTRIES.map(([code, name]) => (
                      <option key={code} value={code}>{name}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Currency">
                  <select className={inputCls} value={currency} onChange={(e) => setCurrency(e.target.value)}>
                    {CURRENCIES.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </Field>
              </div>
              <p className="text-xs text-gray-400">🔒 Your data is encrypted and never shared.</p>
            </div>
          </Section>
        )}

        {/* Step 3 — import transactions */}
        {step === 3 && (
          <Section
            title="Import your transactions"
            sub="Upload a bank statement and Kora's AI categorizes everything. You can skip and add them later."
          >
            <div
              onClick={() => inputRef.current?.click()}
              className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-300 bg-white px-6 py-10 text-center hover:border-kora-400"
            >
              {uploadBusy ? (
                <Loader2 className="animate-spin text-kora-600" size={28} />
              ) : uploadCount !== null ? (
                <Check className="text-emerald-600" size={28} />
              ) : (
                <UploadCloud className="text-kora-600" size={28} />
              )}
              <p className="mt-3 text-sm font-medium text-gray-900">
                {uploadBusy
                  ? 'AI is categorizing your transactions…'
                  : uploadCount !== null
                  ? `Imported ${uploadCount} transactions. P&L will be ready in ~30 seconds.`
                  : 'Drop a bank statement CSV here'}
              </p>
              <p className="mt-1 text-xs text-gray-500">Columns: Date, Description, Amount, Type. Max 5MB.</p>
              <input
                ref={inputRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadCsv(f);
                }}
              />
            </div>
            <a href="/sample-transactions.csv" download className="mt-3 inline-block text-xs font-medium text-kora-600 hover:underline">
              Download a sample CSV
            </a>
          </Section>
        )}

        {/* Step 4 — first client */}
        {step === 4 && (
          <Section
            title="Add your first client"
            sub="So you can invoice them in one click. Optional — add clients anytime."
          >
            <div className="flex flex-col gap-3 sm:flex-row">
              <input className={inputCls} placeholder="Client name" value={clientName} onChange={(e) => setClientName(e.target.value)} />
              <input className={inputCls} placeholder="client@email.com" value={clientEmail} onChange={(e) => setClientEmail(e.target.value)} />
              <button
                onClick={addClient}
                className="inline-flex shrink-0 items-center justify-center gap-1 rounded-lg border border-kora-200 bg-kora-50 px-4 py-2 text-sm font-semibold text-kora-700 hover:bg-kora-100"
              >
                <Plus size={15} /> Add
              </button>
            </div>
            {clients.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {clients.map((c, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 rounded-full bg-white border border-gray-200 px-3 py-1 text-xs text-gray-700">
                    {c.name}
                    <button onClick={() => setClients((cs) => cs.filter((_, j) => j !== i))} className="text-gray-400 hover:text-red-500">
                      <X size={13} />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </Section>
        )}

        {/* Step 5 — ready */}
        {step === 5 && (
          <Section title="Kora is ready" sub="Your AI agents are now monitoring your business 24/7.">
            <div className="grid gap-3 sm:grid-cols-2">
              <StatusCard
                icon={BookOpen}
                title="Bookkeeper"
                active={uploadCount !== null}
                onText="Transactions imported and categorized."
                offText="Upload transactions to start."
              />
              <StatusCard
                icon={FileText}
                title="Invoice agent"
                active={clients.length > 0}
                onText="Ready to invoice your clients."
                offText="Add a client to send invoices."
              />
              <StatusCard icon={Bell} title="Follow-up agent" active onText="AI will chase overdue invoices automatically." />
              <StatusCard icon={FileSignature} title="Contract generator" active onText="Generate NDAs and agreements in plain English." />
            </div>
            <div className="mt-5 rounded-xl bg-kora-50 px-5 py-4 text-sm text-kora-800">
              Kora is monitoring your business 24/7. Your daily digest arrives every morning.
            </div>
          </Section>
        )}

        {error && (
          <div className="mt-5 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        )}

        {/* Nav */}
        <div className="mt-8 flex items-center justify-between">
          <button
            onClick={back}
            disabled={step === 1}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-500 hover:text-gray-900 disabled:invisible"
          >
            <ArrowLeft size={15} /> Back
          </button>

          <div className="flex items-center gap-4">
            {(step === 3 || step === 4) && (
              <button onClick={next} className="text-sm font-medium text-gray-400 hover:text-gray-600">
                Skip
              </button>
            )}
            {step < TOTAL ? (
              <button
                onClick={next}
                disabled={saving}
                className="inline-flex items-center gap-1.5 rounded-lg bg-kora-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
              >
                {saving && <Loader2 size={15} className="animate-spin" />}
                Continue <ArrowRight size={15} />
              </button>
            ) : (
              <button
                onClick={finish}
                disabled={saving}
                className="inline-flex items-center gap-1.5 rounded-lg bg-kora-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
              >
                {saving && <Loader2 size={15} className="animate-spin" />}
                Go to dashboard <ArrowRight size={15} />
              </button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

function Section({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
      <p className="mt-1 text-sm text-gray-500">{sub}</p>
      <div className="mt-6">{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>
      {children}
    </label>
  );
}

function StatusCard({
  icon: Icon,
  title,
  active,
  onText,
  offText,
}: {
  icon: typeof BookOpen;
  title: string;
  active: boolean;
  onText: string;
  offText?: string;
}) {
  return (
    <div className={cn('rounded-xl border p-4', active ? 'border-emerald-200 bg-emerald-50' : 'border-gray-200 bg-white')}>
      <div className="flex items-center gap-2">
        <Icon size={17} className={active ? 'text-emerald-600' : 'text-gray-400'} />
        <p className="text-sm font-semibold text-gray-900">{title}</p>
        {active && <Check size={15} className="ml-auto text-emerald-600" />}
      </div>
      <p className={cn('mt-1.5 text-xs', active ? 'text-emerald-700' : 'text-gray-500')}>
        {active ? onText : offText}
      </p>
    </div>
  );
}
