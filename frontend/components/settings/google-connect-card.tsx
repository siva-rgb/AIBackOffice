'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, PlugZap, PlugZapIcon, CheckCircle2, Unlink } from 'lucide-react';
import { Card, CardHeader } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';

interface Props {
  connected: boolean;
  googleEmail: string | null;
}

export function GoogleConnectCard({ connected, googleEmail }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConnect() {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch('/api/auth/google/connect');
      if (!res.ok) throw new Error('Could not start Google OAuth flow');
      const { auth_url, error: apiError } = await res.json();
      if (apiError) throw new Error(apiError);
      window.location.href = auth_url;
    } catch (e: any) {
      setError(e?.message ?? 'Connection failed');
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    if (!confirm('Disconnect Google? Kora will lose access to Gmail, Calendar and Drive.')) return;
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch('/api/auth/google/disconnect', { method: 'DELETE' });
      if (!res.ok) throw new Error('Disconnect failed');
      router.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Disconnect failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Google Workspace"
        subtitle="Connect Gmail, Calendar and Drive so Kora's Butler agents can act on your behalf"
        action={<PlugZap size={16} className="text-gray-400" />}
      />
      <div className="flex items-center justify-between gap-4 p-5">
        {connected ? (
          <div className="flex items-center gap-2 text-sm text-green-700">
            <CheckCircle2 size={16} className="shrink-0" />
            <span>
              Connected as <span className="font-medium">{googleEmail}</span>
            </span>
          </div>
        ) : (
          <p className="text-sm text-gray-500">Not connected</p>
        )}

        <div className="flex items-center gap-3">
          {error && <span className="text-xs text-red-600">{error}</span>}
          {connected ? (
            <button
              onClick={handleDisconnect}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-60"
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Unlink size={14} />}
              Disconnect
            </button>
          ) : (
            <button
              onClick={handleConnect}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <PlugZapIcon size={14} />}
              Connect Google
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
