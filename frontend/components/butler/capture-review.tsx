'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Check, Loader2, CheckCircle2 } from 'lucide-react';
import { Card, CardHeader } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import { formatDateTime } from '@/lib/utils';
import type { QuickCapture } from '@/lib/api/types';

export function CaptureReview({ captures }: { captures: QuickCapture[] }) {
  const router = useRouter();
  const [items, setItems] = useState(captures);
  const [busy, setBusy] = useState<string | null>(null);

  async function resolve(id: string) {
    setBusy(id);
    try {
      await authedFetch(`/api/butler/captures/${id}/resolve`, { method: 'POST' });
      setItems((xs) => xs.filter((x) => x.id !== id));
      router.refresh();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <Link href="/butler" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft size={15} /> Back to Butler
      </Link>
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Review queue</h1>
        <p className="mt-1 text-sm text-gray-500">Notes Kora wasn&apos;t confident about. Confirm them and they&apos;ll clear.</p>
      </div>
      <Card>
        <CardHeader title="Needs review" />
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-14 text-center">
            <CheckCircle2 className="text-emerald-500" size={28} />
            <p className="mt-3 text-sm font-medium text-gray-900">Everything looks good</p>
            <p className="mt-1 text-sm text-gray-500">Nothing to check right now.</p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {items.map((c) => (
              <li key={c.id} className="flex items-start justify-between gap-3 px-5 py-4">
                <div className="min-w-0">
                  <p className="text-sm text-gray-800">{c.rawText}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {c.parsedIntent ?? 'unknown'}
                    {c.aiConfidence != null && ` · ${Math.round(c.aiConfidence * 100)}% confidence`}
                    {' · '}{formatDateTime(c.createdAt)}
                  </p>
                </div>
                <button onClick={() => resolve(c.id)} disabled={busy === c.id}
                  className="inline-flex shrink-0 items-center gap-1 rounded-md bg-kora-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-kora-700 disabled:opacity-60">
                  {busy === c.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} Mark reviewed
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
