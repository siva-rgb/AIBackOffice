'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { authedFetch } from '@/lib/api/browser';

interface SubscriptionInfo {
  id: string;
  status: string;
  current_period_end: number;
  cancel_at_period_end: boolean;
  plan_amount: number;
}

interface BillingInfo {
  plan: string;
  subscription: SubscriptionInfo | null;
}

export default function BillingSettingsPage() {
  const [billing, setBilling] = useState<BillingInfo | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    authedFetch('/api/stripe/billing')
      .then(r => r.json())
      .then(setBilling)
      .catch(() => {});

    // After Stripe redirects back on success, give webhook time to fire
    const params = new URLSearchParams(window.location.search);
    if (params.get('success') === 'true') {
      setTimeout(() => {
        authedFetch('/api/stripe/billing')
          .then(r => r.json())
          .then(setBilling)
          .catch(() => {});
      }, 2500);
    }
  }, []);

  async function handleCancel() {
    if (
      !confirm(
        "Cancel your subscription? You'll keep access until the end of the current billing period.",
      )
    )
      return;
    setCancelling(true);
    setError(null);
    try {
      const res = await authedFetch('/api/stripe/cancel', { method: 'POST' });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail ?? 'Cancel failed');
      }
      setBilling(prev =>
        prev
          ? {
              ...prev,
              subscription: prev.subscription
                ? { ...prev.subscription, cancel_at_period_end: true }
                : null,
            }
          : null,
      );
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not cancel subscription.');
    } finally {
      setCancelling(false);
    }
  }

  async function handleReactivate() {
    setError(null);
    try {
      const res = await authedFetch('/api/stripe/reactivate', { method: 'POST' });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail ?? 'Reactivate failed');
      }
      const fresh = await authedFetch('/api/stripe/billing').then(r => r.json());
      setBilling(fresh);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not reactivate subscription.');
    }
  }

  async function openCustomerPortal() {
    setError(null);
    try {
      const res = await authedFetch('/api/stripe/portal', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? 'Portal failed');
      window.location.href = data.portal_url;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not open billing portal.');
    }
  }

  if (!billing) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-semibold text-gray-900">Billing</h2>
        <p className="text-sm text-gray-400">Loading…</p>
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="text-xl font-semibold text-gray-900">Billing</h2>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-400">Current plan</p>
            <p className="mt-0.5 text-lg font-semibold capitalize text-gray-900">{billing.plan}</p>
          </div>
          {billing.plan === 'free' && (
            <Link
              href="/pricing"
              className="rounded-lg bg-kora-500 px-4 py-2 text-sm font-medium text-white hover:bg-kora-600"
            >
              Upgrade
            </Link>
          )}
          {billing.plan === 'starter' && (
            <Link
              href="/pricing"
              className="rounded-lg bg-kora-500 px-4 py-2 text-sm font-medium text-white hover:bg-kora-600"
            >
              Upgrade to Pro
            </Link>
          )}
        </div>

        {billing.subscription && (
          <div className="mt-4 space-y-3 border-t border-gray-100 pt-4">
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Status</span>
              <span
                className={
                  billing.subscription.status === 'active' ? 'text-green-600' : 'text-amber-600'
                }
              >
                {billing.subscription.status}
                {billing.subscription.cancel_at_period_end && ' (cancelling)'}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Amount</span>
              <span className="text-gray-900">${billing.subscription.plan_amount}/month</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Period ends</span>
              <span className="text-gray-900">
                {new Date(billing.subscription.current_period_end * 1000).toLocaleDateString()}
              </span>
            </div>

            {billing.subscription.cancel_at_period_end ? (
              <button
                onClick={handleReactivate}
                className="mt-1 text-sm text-kora-600 hover:underline"
              >
                Reactivate subscription
              </button>
            ) : (
              <div className="flex items-center gap-4 pt-1">
                <button
                  onClick={openCustomerPortal}
                  className="text-sm text-kora-600 hover:underline"
                >
                  Manage payment method
                </button>
                <button
                  onClick={handleCancel}
                  disabled={cancelling}
                  className="text-sm text-red-500 hover:underline disabled:opacity-50"
                >
                  {cancelling ? 'Cancelling…' : 'Cancel subscription'}
                </button>
              </div>
            )}
          </div>
        )}

        {billing.plan === 'free' && !billing.subscription && (
          <p className="mt-4 text-sm text-gray-400">
            No active subscription.{' '}
            <Link href="/pricing" className="text-kora-600 hover:underline">
              View plans
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}
