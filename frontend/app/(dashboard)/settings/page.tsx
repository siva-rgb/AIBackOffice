import Link from 'next/link';
import { serverGet } from '@/lib/api/server';
import type { Me } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { ProfileForm } from '@/components/settings/profile-form';
import { GoogleConnectCard } from '@/components/settings/google-connect-card';
import { StripeConnectCard } from '@/components/settings/stripe-connect-card';
import { NotionConnectCard } from '@/components/settings/notion-connect-card';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Settings — Kora' };

interface Props {
  searchParams: {
    google_connected?: string;
    google_error?: string;
    stripe_connect_success?: string;
    stripe_connect_error?: string;
    notion?: string;
  };
}

export default async function SettingsPage({ searchParams }: Props) {
  let me: Me;
  try {
    me = await serverGet<Me>('/api/me');
  } catch {
    return <BackendDown />;
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage your business profile and connected integrations.
        </p>
      </header>

      {searchParams.google_connected && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          Google connected successfully.
        </div>
      )}
      {searchParams.google_error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Google connection failed: {searchParams.google_error}
        </div>
      )}
      {searchParams.stripe_connect_success && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          Stripe connected successfully. Click &quot;Sync now&quot; to import your transactions.
        </div>
      )}
      {searchParams.stripe_connect_error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Stripe connection failed: {searchParams.stripe_connect_error}
        </div>
      )}

      {searchParams.notion === 'connected' && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          Notion connected. Use &quot;Create database&quot; below to set up your Tasks board, then sync.
        </div>
      )}
      {searchParams.notion === 'error' && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Notion connection failed. Please try again.
        </div>
      )}

      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-800">Integrations</h2>
        <GoogleConnectCard
          connected={me.googleConnected ?? false}
          googleEmail={me.googleEmail ?? null}
        />
        <StripeConnectCard />
        <NotionConnectCard />
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-800">Billing</h2>
        <Link
          href="/settings/billing"
          className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 hover:border-kora-300 hover:shadow-sm transition-all"
        >
          <div>
            <p className="text-sm font-semibold text-gray-800">Subscription &amp; billing</p>
            <p className="text-xs text-gray-500 mt-0.5">Manage your plan, payment method, and invoices</p>
          </div>
          <span className="text-gray-400">→</span>
        </Link>
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-800">Agent intelligence</h2>
        <Link
          href="/settings/playbook"
          className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 hover:border-kora-300 hover:shadow-sm transition-all"
        >
          <div>
            <p className="text-sm font-semibold text-gray-800">What Kora knows</p>
            <p className="text-xs text-gray-500 mt-0.5">Review and manage everything Kora has learned about your business</p>
          </div>
          <span className="text-gray-400">→</span>
        </Link>
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-800">Business profile</h2>
        <p className="text-sm text-gray-500">
          The more Kora knows about your business, the better its agents can manage your
          finances, invoices, and contracts on your behalf.
        </p>
        <ProfileForm me={me} />
      </section>
    </div>
  );
}
