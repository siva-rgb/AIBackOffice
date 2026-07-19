'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, Send, Sparkles } from 'lucide-react';
import { authedFetch } from '@/lib/api/browser';

// Always-one-click-away capture. Freeform text → AI parses it into client notes
// / engagement updates. Posts to /api/butler/captures (parsed inline).
export function QuickCapture() {
  const router = useRouter();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  async function submit() {
    if (!text.trim() || busy) return;
    setBusy(true);
    setFlash(null);
    try {
      const res = await authedFetch('/api/butler/captures', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: text.trim(), source: 'web' }),
      });
      const json = await res.json();
      if (!res.ok) {
        setFlash(typeof json.detail === 'string' ? json.detail : "Couldn't save that note.");
      } else {
        const actions = (json.actionsTaken ?? []).length;
        setFlash(
          actions > 0
            ? `Got it — Kora updated ${actions} thing${actions === 1 ? '' : 's'}.`
            : json.requiresReview
              ? 'Saved — Kora flagged it for your review.'
              : 'Got it.',
        );
        setText('');
        router.refresh();
        setTimeout(() => setFlash(null), 3500);
      }
    } catch {
      setFlash("Couldn't reach Kora just now.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed bottom-0 left-60 right-0 z-30 border-t border-gray-200 bg-white/95 px-8 py-3 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-2">
        <Sparkles size={16} className="shrink-0 text-kora-500" />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="Tell Kora something… e.g. “Finished the Harbor Co website” or “Acme is delayed on copy”"
          maxLength={2000}
          disabled={busy}
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500"
        />
        {flash && <span className="hidden text-xs text-kora-700 sm:inline">{flash}</span>}
        <button
          onClick={submit}
          disabled={!text.trim() || busy}
          className="inline-flex items-center gap-1.5 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-50"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Log
        </button>
      </div>
    </div>
  );
}
