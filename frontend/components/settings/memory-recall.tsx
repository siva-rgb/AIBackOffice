'use client';

import { useEffect, useState } from 'react';
import { Search, Loader2, Sparkles, RefreshCw, Brain } from 'lucide-react';
import { Card } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import type { MemoryHit, MemoryRecallResult, MemoryStats } from '@/lib/api/types';

const KIND_LABEL: Record<string, string> = {
  playbook: 'Preference / rule',
  graph_fact: 'Learned fact',
  email_intel: 'Email',
  meeting: 'Meeting',
  note: 'Note',
  decision: 'Decision',
  action: 'Action',
};

const EXAMPLES = [
  'client refusing to settle their invoice',
  'past pushback on pricing',
  'who pays late',
  'what did we agree on scope',
];

function scorePct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

export function MemoryRecall() {
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [hits, setHits] = useState<MemoryHit[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [reindexing, setReindexing] = useState(false);

  async function loadStats() {
    try {
      const res = await authedFetch('/api/memory/stats');
      if (res.ok) setStats(await res.json());
    } catch {
      /* best-effort */
    }
  }

  useEffect(() => {
    loadStats();
  }, []);

  async function search(q: string) {
    const term = q.trim();
    if (!term) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch('/api/memory/recall', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: term, k: 8 }),
      });
      if (!res.ok) throw new Error();
      const data: MemoryRecallResult = await res.json();
      setHits(data.results);
    } catch {
      setErr('Recall failed. If this is a fresh setup, apply the semantic-memory migration first.');
      setHits(null);
    } finally {
      setBusy(false);
    }
  }

  async function reindex() {
    setReindexing(true);
    setErr(null);
    try {
      const res = await authedFetch('/api/memory/reindex', { method: 'POST' });
      if (!res.ok) throw new Error();
      await loadStats();
    } catch {
      setErr('Reindex failed. Ensure the semantic-memory migration is applied.');
    } finally {
      setReindexing(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Stats + reindex */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-sm text-gray-500">
          {stats ? (
            <>
              <span>
                {stats.total} memor{stats.total === 1 ? 'y' : 'ies'} indexed · {stats.embedded} embedded
              </span>
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  stats.embeddingsEnabled ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'
                }`}
                title={
                  stats.embeddingsEnabled
                    ? 'Semantic ranking active (embeddings)'
                    : 'Lexical-only ranking — set EMBEDDING_MODEL to enable semantic'
                }
              >
                {stats.embeddingsEnabled ? 'Semantic' : 'Lexical only'}
              </span>
            </>
          ) : (
            <span>Loading memory stats…</span>
          )}
        </p>
        <button
          onClick={reindex}
          disabled={reindexing}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-60"
        >
          {reindexing ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Reindex
        </button>
      </div>

      {/* Search box */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          search(query);
        }}
        className="flex gap-2"
      >
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask by meaning — e.g. “client refusing to settle their invoice”"
            className="w-full rounded-lg border border-gray-200 py-2.5 pl-9 pr-3 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500"
          />
        </div>
        <button
          type="submit"
          disabled={busy || !query.trim()}
          className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Brain size={15} />} Recall
        </button>
      </form>

      {/* Example chips */}
      {!hits && !busy && (
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => {
                setQuery(ex);
                search(ex);
              }}
              className="rounded-full border border-gray-200 px-3 py-1 text-xs text-gray-500 hover:border-kora-300 hover:text-kora-700"
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      {err && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{err}</div>}

      {/* Results */}
      {hits && (
        <div className="space-y-2">
          {hits.length === 0 ? (
            <Card className="p-8 text-center">
              <Sparkles className="mx-auto text-gray-300" size={26} />
              <p className="mt-3 text-sm font-medium text-gray-500">No relevant memories found</p>
              <p className="mt-1 text-xs text-gray-400">
                Memories accrue as Kora learns from your email, meetings and corrections. Try “Reindex” to
                backfill from what it already knows.
              </p>
            </Card>
          ) : (
            hits.map((h, i) => (
              <Card key={i} className="p-3.5">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex w-12 shrink-0 flex-col items-center">
                    <span className="text-sm font-bold text-kora-700">{scorePct(h.score)}</span>
                    <span className="text-[9px] uppercase tracking-wide text-gray-400">match</span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-gray-800">{h.content}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-gray-400">
                      <span className="rounded bg-gray-100 px-1.5 py-0.5 font-medium text-gray-500">
                        {KIND_LABEL[h.kind] ?? h.kind}
                      </span>
                      {h.similarity !== null && <span>semantic {scorePct(h.similarity)}</span>}
                      <span>lexical {scorePct(h.lexical)}</span>
                      {h.source && <span>· {h.source}</span>}
                    </div>
                  </div>
                </div>
              </Card>
            ))
          )}
        </div>
      )}
    </div>
  );
}
