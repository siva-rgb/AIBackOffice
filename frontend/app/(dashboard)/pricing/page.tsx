'use client';

import { useState, useEffect } from 'react';
import { authedFetch } from '@/lib/api/browser';


interface BillingStatus {
  plan: string;
  subscription: { status: string } | null;
}

const PLANS = [
  {
    id: 'free',
    name: 'Free',
    price: '$0',
    period: 'forever',
    features: ['20 transactions/month', '1 contract/month', 'Manual invoicing'],
    priceId: null as string | null,
  },
  {
    id: 'starter',
    name: 'Starter',
    price: '$29',
    period: '/month',
    features: [
      'Unlimited transactions',
      'Invoice follow-up agent',
      'Proactive AI alerts',
      'Morning briefing',
      'Quick capture',
    ],
    priceId: process.env.NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID ?? null,
    popular: true,
  },
  {
    id: 'pro',
    name: 'Pro',
    price: '$49',
    period: '/month',
    features: [
      'Everything in Starter',
      'Contract generator',
      'Proposal generator',
      'Cash flow forecast',
      'Full Butler + Google intel',
      'Retainer tracking',
    ],
    priceId: process.env.NEXT_PUBLIC_STRIPE_PRO_PRICE_ID ?? null,
  },
];

export default function PricingPage() {
  const [loading, setLoading] = useState<string | null>(null);
  const [currentPlan, setCurrentPlan] = useState<string>('free');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    authedFetch('/api/stripe/billing')
      .then(r => r.json())
      .then((data: BillingStatus) => setCurrentPlan(data.plan ?? 'free'))
      .catch(() => {});
  }, []);

  async function handleSubscribe(priceId: string) {
    setLoading(priceId);
    setError(null);
    try {
      const res = await authedFetch('/api/stripe/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ priceId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? 'Checkout failed');
      window.location.href = data.checkout_url;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to start checkout. Please try again.');
      setLoading(null);
    }
  }

  async function handleUpgrade(priceId: string) {
    setLoading(priceId);
    setError(null);
    try {
      const res = await authedFetch('/api/stripe/upgrade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ newPriceId: priceId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? 'Upgrade failed');
      setCurrentPlan(data.plan);
      setLoading(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to change plan. Please try again.');
      setLoading(null);
    }
  }

  function getButtonState(plan: (typeof PLANS)[0]) {
    if (plan.id === currentPlan) {
      return { label: 'Current plan', action: null, disabled: true, variant: 'outline' };
    }
    if (plan.id === 'free') {
      return {
        label: 'Cancel to downgrade',
        action: null,
        disabled: true,
        variant: 'outline',
        hint: 'Cancel from Settings → Billing',
      };
    }
    if (currentPlan === 'free') {
      return {
        label: `Subscribe to ${plan.name}`,
        action: () => handleSubscribe(plan.priceId!),
        disabled: false,
        variant: 'primary',
      };
    }
    const isUpgrade =
      PLANS.findIndex(p => p.id === plan.id) > PLANS.findIndex(p => p.id === currentPlan);
    return {
      label: isUpgrade ? `Upgrade to ${plan.name}` : `Switch to ${plan.name}`,
      action: () => handleUpgrade(plan.priceId!),
      disabled: false,
      variant: isUpgrade ? 'primary' : 'outline',
    };
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Plans</h1>
        <p className="mt-1 text-sm text-gray-500">Start free. Upgrade when you&apos;re ready.</p>
      </header>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {PLANS.map(plan => {
          const btn = getButtonState(plan);
          const isCurrent = plan.id === currentPlan;
          return (
            <div
              key={plan.id}
              className={`rounded-xl border bg-white p-6 shadow-sm ${
                isCurrent ? 'border-kora-400 ring-1 ring-kora-400' : 'border-gray-200'
              } ${'popular' in plan && plan.popular && !isCurrent ? 'border-kora-200' : ''}`}
            >
              {isCurrent && (
                <span className="mb-2 block text-xs font-medium text-kora-600">
                  Your current plan
                </span>
              )}
              {'popular' in plan && plan.popular && !isCurrent && (
                <span className="mb-2 block text-xs font-medium text-gray-400">Most popular</span>
              )}
              <h3 className="text-lg font-semibold text-gray-900">{plan.name}</h3>
              <div className="mb-4 mt-2">
                <span className="text-3xl font-bold text-gray-900">{plan.price}</span>
                <span className="text-sm text-gray-500">{plan.period}</span>
              </div>
              <ul className="mb-6 space-y-2">
                {plan.features.map(f => (
                  <li key={f} className="flex gap-2 text-sm text-gray-700">
                    <span className="mt-0.5 text-green-500">✓</span> {f}
                  </li>
                ))}
              </ul>
              <button
                onClick={btn.action ?? undefined}
                disabled={btn.disabled || loading === plan.priceId}
                className={`w-full rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 ${
                  btn.variant === 'primary'
                    ? 'bg-kora-500 text-white hover:bg-kora-600'
                    : 'border border-gray-300 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {loading === plan.priceId ? 'Processing…' : btn.label}
              </button>
              {'hint' in btn && btn.hint && (
                <p className="mt-2 text-center text-xs text-gray-400">{btn.hint}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
