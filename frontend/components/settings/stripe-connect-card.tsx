'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, PlugZap, CheckCircle2, Unlink, RefreshCw } from 'lucide-react';
import { Card, CardHeader } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';

interface ConnectStatus {
  connected: boolean;
  email?: string;
  account_id?: string;
  last_sync?: string;
  last_sync_count?: number;
  livemode?: boolean;
}

interface Props {
  initialStatus?: ConnectStatus;
}

export function StripeConnectCard({ initialStatus }: Props) {
  const router = useRouter();
  const [status, setStatus] = useState<ConnectStatus>(initialStatus ?? { connected: false });
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    authedFetch('/api/stripe-connect/status')
      .then(r => r.json())
      .then(setStatus)
      .catch(() => {});
  }, []);

  async function handleConnect() {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch('/api/stripe-connect/connect');
      if (!res.ok) throw new Error('Could not start Stripe OAuth flow');
      const { auth_url, error: apiError } = await res.json();
      if (apiError) throw new Error(apiError);
      window.location.href = auth_url;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Connection failed');
      setBusy(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    setSyncResult(null);
    setError(null);
    try {
      const res = await authedFetch('/api/stripe-connect/sync', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? 'Sync failed');
      const msg =
        data.synced_count > 0
          ? `Synced ${data.synced_count} new transaction${data.synced_count !== 1 ? 's' : ''}`
          : 'No new transactions found';
      setSyncResult(msg);
      // Refresh the status to show updated last_sync time
      const fresh = await authedFetch('/api/stripe-connect/status').then(r => r.json());
      setStatus(fresh);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sync failed');
    } finally {
      setSyncing(false);
    }
  }

  async function handleDisconnect() {
    if (!confirm('Disconnect your Stripe account? Kora will stop syncing transactions.')) return;
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch('/api/stripe-connect/disconnect', { method: 'DELETE' });
      if (!res.ok) throw new Error('Disconnect failed');
      setStatus({ connected: false });
      router.refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Disconnect failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Stripe Account"
        subtitle="Auto-import charges, refunds, and fees for bookkeeping (read-only)"
        action={<PlugZap size={16} className="text-gray-400" />}
      />
      <div className="p-5 space-y-4">
        <div className="flex items-center justify-between gap-4">
          {status.connected ? (
            <div className="flex items-center gap-2 text-sm text-green-700">
              <CheckCircle2 size={16} className="shrink-0" />
              <span>
                Connected as{' '}
                <span className="font-medium">{status.email ?? status.account_id}</span>
                {status.livemode === false && (
                  <span className="ml-2 text-xs text-amber-600">(test mode)</span>
                )}
              </span>
            </div>
          ) : (
            <p className="text-sm text-gray-500">Not connected</p>
          )}

          <div className="flex items-center gap-2 shrink-0">
            {error && <span className="text-xs text-red-600">{error}</span>}
            {status.connected ? (
              <>
                <button
                  onClick={handleSync}
                  disabled={syncing || busy}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
                >
                  {syncing ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <RefreshCw size={13} />
                  )}
                  {syncing ? 'Syncing…' : 'Sync now'}
                </button>
                <button
                  onClick={handleDisconnect}
                  disabled={busy || syncing}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-60"
                >
                  {busy ? <Loader2 size={13} className="animate-spin" /> : <Unlink size={13} />}
                  Disconnect
                </button>
              </>
            ) : (
              <button
                onClick={handleConnect}
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
                Connect Stripe
              </button>
            )}
          </div>
        </div>

        {syncResult && (
          <p className="text-sm text-green-700">{syncResult} — check Bookkeeping to review.</p>
        )}

        {status.connected && status.last_sync && (
          <p className="text-xs text-gray-400">
            Last synced: {new Date(status.last_sync).toLocaleString()} ·{' '}
            {status.last_sync_count ?? 0} transactions
          </p>
        )}

        {!status.connected && (
          <div className="rounded-lg bg-gray-50 px-4 py-3 text-sm text-gray-500 space-y-1">
            <p className="font-medium text-gray-700">What Kora will access (read-only):</p>
            <ul className="space-y-0.5">
              <li>✓ Incoming payments (charges)</li>
              <li>✓ Refunds and adjustments</li>
              <li>✓ Stripe processing fees</li>
              <li className="text-gray-400">✗ Kora cannot create charges or move money</li>
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}
