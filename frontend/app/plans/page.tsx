import Link from 'next/link';
import { Check, Sparkles } from 'lucide-react';
import { PublicHeader } from '@/components/marketing/public-header';
import { API_BASE } from '@/lib/api/config';

export const metadata = {
  title: 'Plans & pricing: Kora',
  description: 'Kora pricing. Early users get the full Pro suite free for 90 days.',
};

// Public page, so the tiers are fetched on the server: no CORS, no auth, and the
// visitor gets HTML with the content already in it. The list itself comes from
// the same table that enforces access, so this page cannot advertise a feature
// the product does not actually unlock.
export const dynamic = 'force-dynamic';

interface Plan {
  id: string;
  name: string;
  price: string;
  period: string;
  tagline: string;
  features: string[];
  popular: boolean;
}

async function getPlans(): Promise<Plan[]> {
  try {
    const res = await fetch(`${API_BASE}/api/plans`, { cache: 'no-store' });
    if (!res.ok) return [];
    const data = await res.json();
    return data.plans ?? [];
  } catch {
    return [];
  }
}

const TRIAL_DAYS = 90;

export default async function PlansPage() {
  const plans = await getPlans();

  return (
    <main className="min-h-screen bg-white">
      <PublicHeader current="plans" />

      <section className="mx-auto max-w-3xl px-6 pt-10 text-center">
        <span className="inline-flex items-center gap-2 rounded-full bg-kora-50 px-4 py-1.5 text-sm font-medium text-kora-700">
          <Sparkles size={15} /> Launch offer: free for early users
        </span>
        <h1 className="mt-6 text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
          Get the full suite free for {TRIAL_DAYS} days.
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-gray-600">
          We&apos;re just launching, so early users get everything. Sign up now and your account is
          upgraded to <strong className="text-gray-900">Pro</strong> for {TRIAL_DAYS} days: every
          agent, contract drafting, cash-flow forecasting, the lot. No card, no trial banner nagging
          you.
        </p>
        <p className="mx-auto mt-3 max-w-2xl text-sm text-gray-500">
          After {TRIAL_DAYS} days your account moves to the Free plan and keeps working. Your data,
          invoices and books stay exactly where they are. Upgrade only if you want the paid features
          back.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/signup"
            className="rounded-lg bg-kora-600 px-6 py-3 text-sm font-semibold text-white hover:bg-kora-700"
          >
            Claim {TRIAL_DAYS} days of Pro
          </Link>
          <Link
            href="/login"
            className="rounded-lg border border-gray-300 px-6 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            I already have an account
          </Link>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-16">
        {plans.length === 0 ? (
          <p className="text-center text-sm text-gray-500">
            Plan details are loading. Please refresh in a moment.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
            {plans.map((plan) => (
              <div
                key={plan.id}
                className={`relative flex flex-col rounded-xl border bg-white p-6 shadow-sm ${
                  plan.popular ? 'border-kora-300 ring-1 ring-kora-200' : 'border-gray-200'
                }`}
              >
                {plan.id === 'pro' && (
                  <span className="absolute -top-3 left-6 rounded-full bg-kora-600 px-3 py-1 text-xs font-semibold text-white">
                    Free for {TRIAL_DAYS} days
                  </span>
                )}
                <h2 className="text-lg font-semibold text-gray-900">{plan.name}</h2>
                <div className="mt-2">
                  <span className="text-3xl font-bold tabular-nums text-gray-900">
                    {plan.price}
                  </span>
                  <span className="text-sm text-gray-500">{plan.period}</span>
                </div>
                <p className="mt-2 text-sm text-gray-500">{plan.tagline}</p>
                <ul className="my-6 flex-1 space-y-2">
                  {plan.features.map((f) => (
                    <li key={f} className="flex gap-2 text-sm text-gray-700">
                      <Check size={16} className="mt-0.5 shrink-0 text-emerald-500" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href="/signup"
                  className={`rounded-lg px-4 py-2 text-center text-sm font-medium ${
                    plan.id === 'pro'
                      ? 'bg-kora-600 text-white hover:bg-kora-700'
                      : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {plan.id === 'free' ? 'Start free' : `Get started`}
                </Link>
              </div>
            ))}
          </div>
        )}

        <div className="mx-auto mt-14 max-w-2xl rounded-xl border border-gray-200 bg-gray-50 p-6">
          <h3 className="text-sm font-semibold text-gray-900">The small print, in plain English</h3>
          <ul className="mt-3 space-y-2 text-sm text-gray-600">
            <li>
              • No credit card to start. We don&apos;t ask for one during the {TRIAL_DAYS} days.
            </li>
            <li>
              • Nothing charges automatically when the {TRIAL_DAYS} days end. You drop to Free.
            </li>
            <li>• Your data is yours. Export it any time, delete your account any time.</li>
            <li>• Payments run through Stripe. Kora never sees or stores your card details.</li>
          </ul>
        </div>
      </section>

      <footer className="border-t border-gray-100 px-6 py-8 text-center text-sm text-gray-500">
        Questions about pricing?{' '}
        <a href="mailto:pandasivananda@gmail.com" className="text-kora-600 hover:underline">
          pandasivananda@gmail.com
        </a>
        {' · '}
        <Link href="/about" className="text-kora-600 hover:underline">
          About Kora
        </Link>
      </footer>
    </main>
  );
}
