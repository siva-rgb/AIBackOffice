'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, Sparkles } from 'lucide-react';
import { authedFetch } from '@/lib/api/browser';

// Runs the daily-digest alert agent on demand (the Cloud Scheduler path in
// production). Lets judges/users see the alert agent fire live.
export function RunDigestButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      await authedFetch('/api/alerts/digest', { method: 'POST' });
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={run}
      disabled={busy}
      className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
    >
      {busy ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
      Run digest
    </button>
  );
}
