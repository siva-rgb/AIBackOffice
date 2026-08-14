'use client';

import { useState, useEffect } from 'react';
import { Check, Loader2 } from 'lucide-react';
import { authedFetch } from '@/lib/api/browser';
import { Skeleton } from '@/components/ui';

/*
 * The tiers are FETCHED, not declared here.
 *
 * This page used to hold its own copy of the plan comparison. It drifted from
 * the server's entitlement table and ended up advertising the cash-flow
 * forecast as Pro when Starter unlocks it, selling several capabilities nothing
 * gates, and omitting two that genuinely are paid. Rendering what the server
 * enforces is the only arrangement in which the page cannot be wrong.
 *
 * Stripe price ids arrive in the same payload rather than being inlined from
 * NEXT_PUBLIC_* at build time, so rotating a price no longer needs a rebuild.
 */

interface Plan {
  id: string;
  name: string;
  price: string;
  period: string;
  tagline: string;
  features: string[];
  priceId: string | null;
  popular: boolean;
}

interface BillingStatus {
  plan: string;
  subscription: { status: string } | null;
}

export default function PricingPage() {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [currentPlan, setCurrentPlan] = useState<string>('free');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    authedFetch('/api/plans')
      .then(r => r.json())
      .then((data: { plans: Plan[] }) => setPlans(data.plans ?? []))
      .catch(() => setError('Could not load plans. Please refresh.'));

    authedFetch('/api/stripe/billing')
      .then(r => r.json())
      .then((data: BillingStatus) => setCurrentPlan(data.plan ?? 'free'))
      .catch(() => {});
  }, []);

  async function post(path: string, body: object, onDone: (data: { plan?: string; checkout_url?: string }) => void) {
    setError(null);
    try {
      const res = await authedFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? 'Something went wrong');
      onDone(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Please try again.');
      setPending(null);
    }
  }

  function subscribe(priceId: string) {
    setPending(priceId);
    post('/api/stripe/checkout', { priceId }, data => {
      if (data.checkout_url) window.location.href = data.checkout_url;
      else setPending(null);
    });
  }

  function changePlan(priceId: string) {
    setPending(priceId);
    post('/api/stripe/upgrade', { newPriceId: priceId }, data => {
      if (data.plan) setCurrentPlan(data.plan);
      setPending(null);
    });
  }

  function buttonFor(plan: Plan, index: number, all: Plan[]) {
    if (plan.id === currentPlan) {
      return { label: 'Current plan', onClick: undefined, disabled: true, primary: false };
    }
    if (plan.id === 'free') {
      return {
        label: 'Downgrade',
        onClick: undefined,
        disabled: true,
        primary: false,
        hint: 'Cancel from Settings → Billing',
      };
    }
    if (!plan.priceId) {
      // Checkout genuinely cannot work without a configured price, so say that
      // rather than showing a button that fails after the click.
      return { label: 'Unavailable', onClick: undefined, disabled: true, primary: false, hint: 'Billing not configured' };
    }
    const priceId = plan.priceId;
    const isUpgrade = index > all.findIndex(p => p.id === currentPlan);
    return {
      label: currentPlan === 'free' ? `Choose ${plan.name}` : isUpgrade ? `Upgrade to ${plan.name}` : `Switch to ${plan.name}`,
      onClick: () => (currentPlan === 'free' ? subscribe(priceId) : changePlan(priceId)),
      disabled: false,
      primary: isUpgrade,
    };
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Plans &amp; pricing</h1>
        <p className="mt-1 text-sm text-gray-500">
          Everything below is what each plan actually unlocks — the list is served by the same table that
          enforces access.
        </p>
      </header>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {plans === null ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {[0, 1, 2].map(i => (
            <div key={i} className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="mt-4 h-8 w-28" />
              <div className="mt-6 space-y-3">
                {[0, 1, 2, 3].map(j => (
                  <Skeleton key={j} className="h-3 w-full" />
                ))}
              </div>
              <Skeleton className="mt-6 h-9 w-full" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {plans.map((plan, i) => {
            const btn = buttonFor(plan, i, plans);
            const isCurrent = plan.id === currentPlan;
            return (
              <div
                key={plan.id}
                className={`relative flex flex-col rounded-xl border bg-white p-6 shadow-sm ${
                  isCurrent ? 'border-kora-400 ring-1 ring-kora-400' : plan.popular ? 'border-kora-200' : 'border-gray-200'
                }`}
              >
                {isCurrent ? (
                  <span className="mb-2 block text-xs font-medium text-kora-600">Your current plan</span>
                ) : plan.popular ? (
                  <span className="mb-2 block text-xs font-medium text-gray-400">Most popular</span>
                ) : (
                  <span className="mb-2 block text-xs">&nbsp;</span>
                )}

                <h2 className="text-lg font-semibold text-gray-900">{plan.name}</h2>
                <div className="mt-2">
                  <span className="text-3xl font-bold tabular-nums text-gray-900">{plan.price}</span>
                  <span className="text-sm text-gray-500">{plan.period}</span>
                </div>
                <p className="mt-2 text-sm text-gray-500">{plan.tagline}</p>

                <ul className="my-6 flex-1 space-y-2">
                  {plan.features.map(f => (
                    <li key={f} className="flex gap-2 text-sm text-gray-700">
                      <Check size={16} className="mt-0.5 shrink-0 text-emerald-500" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>

                <button
                  onClick={btn.onClick}
                  disabled={btn.disabled || pending === plan.priceId}
                  className={`flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 ${
                    btn.primary
                      ? 'bg-kora-500 text-white hover:bg-kora-600'
                      : 'border border-gray-300 text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {pending === plan.priceId && <Loader2 size={16} className="animate-spin" />}
                  {pending === plan.priceId ? 'Opening checkout…' : btn.label}
                </button>
                {'hint' in btn && btn.hint && (
                  <p className="mt-2 text-center text-xs text-gray-400">{btn.hint}</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="text-xs text-gray-400">
        Prices in USD, billed monthly. Cancel any time from Settings → Billing.
      </p>
    </div>
  );
}
