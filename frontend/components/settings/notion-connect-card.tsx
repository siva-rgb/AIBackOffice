'use client';

import { useEffect, useState } from 'react';
import { Loader2, BookOpen, ExternalLink, CheckCircle2, Unlink, RefreshCw } from 'lucide-react';
import { authedFetch } from '@/lib/api/browser';

interface NotionStatus {
  connected: boolean;
  authMode: 'oauth' | 'api_key' | null;
  workspaceName: string | null;
  selectedPageIds: string[];
  selectedPageCount: number;
  lastIngestAt: string | null;
  lastError: string | null;
  oauthConfigured: boolean;
}

interface NotionPage {
  id: string;
  title: string;
  url: string | null;
}

// Notion is a READ-ONLY intelligence source: connect, pick the pages Kora may
// read, and Kora folds their content into its memory. It never writes back.
export function NotionConnectCard() {
  const [status, setStatus] = useState<NotionStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [pages, setPages] = useState<NotionPage[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  async function load() {
    try {
      const res = await authedFetch('/api/notion/status');
      if (res.ok) {
        const s: NotionStatus = await res.json();
        setStatus(s);
        setSelected(new Set(s.selectedPageIds ?? []));
      }
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

  async function disconnect() {
    setBusy('disconnect');
    setMsg(null);
    try {
      const res = await authedFetch('/api/notion/disconnect', { method: 'DELETE' });
      if (!res.ok && res.status !== 204) throw new Error();
      setPages(null);
      setSelected(new Set());
      setMsg({ text: 'Notion disconnected. Kora forgot everything it read from it.', ok: true });
      await load();
    } catch {
      setMsg({ text: 'Could not disconnect.', ok: false });
    } finally {
      setBusy(null);
    }
  }

  async function loadPages() {
    setBusy('pages');
    setMsg(null);
    try {
      const res = await authedFetch('/api/notion/pages');
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setPages(data.pages ?? []);
      if ((data.pages ?? []).length === 0) {
        setMsg({
          text: 'No pages available. In Notion, open a page you want Kora to read → ⋯ → Connections → add KORA, then retry.',
          ok: false,
        });
      }
    } catch (e: any) {
      setMsg({ text: e?.message ?? 'Could not list your Notion pages.', ok: false });
    } finally {
      setBusy(null);
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function saveSelection() {
    setBusy('save');
    setMsg(null);
    try {
      const res = await authedFetch('/api/notion/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pageIds: Array.from(selected) }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? 'Could not save.');
      setMsg({ text: 'Saved. Reading those pages into Kora’s memory…', ok: true });
      // Kick an ingest so the content is available right away.
      await authedFetch('/api/notion/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      await load();
    } catch (e: any) {
      setMsg({ text: e?.message ?? 'Could not save your selection.', ok: false });
    } finally {
      setBusy(null);
    }
  }

  async function reingest() {
    setBusy('ingest');
    setMsg(null);
    try {
      const res = await authedFetch('/api/notion/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? 'Ingest failed');
      setMsg({ text: `Read ${data.pages ?? 0} page(s) into memory (${data.chunks ?? 0} snippet(s)).`, ok: true });
      await load();
    } catch (e: any) {
      setMsg({ text: e?.message ?? 'Could not read your pages.', ok: false });
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
            <BookOpen size={16} className="text-gray-400" />
            <p className="text-sm font-semibold text-gray-800">Notion</p>
            {connected && (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                <CheckCircle2 size={10} /> Connected
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-gray-500">
            Already keep notes in Notion? Connect it and pick the pages Kora may read. Kora folds
            their content into its memory and uses it when it reasons about your clients —{' '}
            <span className="font-medium text-gray-600">read-only, it never writes to your Notion.</span>
          </p>
          {connected && (
            <p className="mt-1 text-[11px] text-gray-400">
              {status?.workspaceName ? `${status.workspaceName} · ` : ''}
              {status?.selectedPageCount
                ? `${status.selectedPageCount} page(s) shared`
                : 'No pages selected yet'}
              {status?.lastIngestAt ? ` · last read ${new Date(status.lastIngestAt).toLocaleString()}` : ''}
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
              <button
                onClick={() => (pages === null ? loadPages() : reingest())}
                disabled={busy !== null || (pages !== null && status?.selectedPageCount === 0)}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-60"
              >
                {busy === 'pages' || busy === 'ingest'
                  ? <Loader2 size={13} className="animate-spin" />
                  : <RefreshCw size={13} />}
                {pages === null ? 'Choose pages' : 'Re-read now'}
              </button>
              <button
                onClick={disconnect}
                disabled={busy !== null}
                title="Disconnect and forget what Kora read"
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-500 hover:bg-red-50 hover:text-red-600 disabled:opacity-60"
              >
                {busy === 'disconnect' ? <Loader2 size={13} className="animate-spin" /> : <Unlink size={13} />}
                Disconnect
              </button>
            </>
          )}
        </div>
      </div>

      {/* Page picker — the user chooses which of their pages Kora may read. */}
      {connected && pages !== null && pages.length > 0 && (
        <div className="mt-3 rounded-lg bg-gray-50 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
            Pages Kora may read
          </p>
          <div className="mt-2 max-h-52 space-y-1 overflow-y-auto">
            {pages.map((p) => (
              <label key={p.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-white">
                <input
                  type="checkbox"
                  checked={selected.has(p.id)}
                  onChange={() => toggle(p.id)}
                  className="h-3.5 w-3.5 rounded border-gray-300 text-kora-600 focus:ring-kora-500"
                />
                <span className="truncate text-gray-700">{p.title}</span>
              </label>
            ))}
          </div>
          <div className="mt-2 flex items-center justify-between">
            <p className="text-[11px] text-gray-400">{selected.size} selected</p>
            <button
              onClick={saveSelection}
              disabled={busy === 'save'}
              className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
            >
              {busy === 'save' ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
              Save &amp; read
            </button>
          </div>
        </div>
      )}

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
