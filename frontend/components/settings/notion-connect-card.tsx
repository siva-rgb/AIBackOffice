'use client';

import { useEffect, useState } from 'react';
import { Loader2, RefreshCw, Database, ExternalLink, CheckCircle2 } from 'lucide-react';
import { authedFetch } from '@/lib/api/browser';

interface NotionStatus {
  connected: boolean;
  authMode: 'oauth' | 'api_key' | null;
  workspaceName: string | null;
  tasksDbId: string | null;
  provisioned: boolean;
  lastSyncAt: string | null;
  lastError: string | null;
  oauthConfigured: boolean;
}

export function NotionConnectCard() {
  const [status, setStatus] = useState<NotionStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  async function load() {
    try {
      const res = await authedFetch('/api/notion/status');
      if (res.ok) setStatus(await res.json());
    } catch {
      /* best-effort */
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function connect() {
    setBusy('connect');
    setMsg(null);
    try {
      const res = await authedFetch('/api/notion/connect');
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      window.location.href = data.authorizeUrl;
    } catch (e: any) {
      setMsg({ text: e?.message ?? 'Could not start the Notion connection.', ok: false });
      setBusy(null);
    }
  }

  async function run(path: string, label: string) {
    setBusy(label);
    setMsg(null);
    try {
      const res = await authedFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? 'Request failed');
      setMsg({
        text: label === 'provision'
          ? 'Tasks database created in your Notion workspace.'
          : `Synced — ${data.pushed ?? 0} pushed, ${data.updated ?? 0} updated from Notion.`,
        ok: true,
      });
      await load();
    } catch (e: any) {
      setMsg({ text: e?.message ?? 'Something went wrong.', ok: false });
    } finally {
      setBusy(null);
    }
  }

  const connected = status?.connected ?? false;

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Database size={16} className="text-gray-400" />
            <p className="text-sm font-semibold text-gray-800">Notion</p>
            {connected && (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                <CheckCircle2 size={10} /> Connected
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-gray-500">
            Mirror your task ledger into Notion. Kora stays the source of truth — edits you make in
            Notion (status, due date, priority) sync back.
          </p>
          {connected && (
            <p className="mt-1 text-[11px] text-gray-400">
              {status?.workspaceName ? `${status.workspaceName} · ` : ''}
              {status?.provisioned ? 'Tasks database ready' : 'Not provisioned yet'}
              {status?.lastSyncAt ? ` · last sync ${new Date(status.lastSyncAt).toLocaleString()}` : ''}
            </p>
          )}
        </div>

        <div className="flex shrink-0 gap-2">
          {!connected ? (
            <button
              onClick={connect}
              disabled={busy === 'connect' || !(status?.oauthConfigured ?? false)}
              title={status?.oauthConfigured ? 'Connect your Notion workspace' : 'Set NOTION_OAUTH_CLIENT_ID/SECRET (or NOTION_API_KEY) first'}
              className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-kora-700 disabled:opacity-50"
            >
              {busy === 'connect' ? <Loader2 size={13} className="animate-spin" /> : <ExternalLink size={13} />}
              Connect
            </button>
          ) : (
            <>
              {!status?.provisioned && (
                <button
                  onClick={() => run('/api/notion/provision', 'provision')}
                  disabled={busy !== null}
                  className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
                >
                  {busy === 'provision' ? <Loader2 size={13} className="animate-spin" /> : <Database size={13} />}
                  Create database
                </button>
              )}
              <button
                onClick={() => run('/api/notion/sync', 'sync')}
                disabled={busy !== null}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-60"
              >
                {busy === 'sync' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                Sync now
              </button>
            </>
          )}
        </div>
      </div>

      {(msg || status?.lastError) && (
        <div
          className={`mt-3 rounded-lg px-3 py-2 text-xs ${
            msg?.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'
          }`}
        >
          {msg?.text ?? status?.lastError}
        </div>
      )}
    </div>
  );
}
