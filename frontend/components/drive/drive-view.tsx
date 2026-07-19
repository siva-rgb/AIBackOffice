'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { HardDrive, RefreshCw, Loader2, FileText, Video, FileSignature, Receipt, File } from 'lucide-react';
import { Card } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import { formatDate } from '@/lib/utils';
import type { DriveDoc } from '@/lib/api/types';

const DOC_ICON: Record<string, typeof File> = {
  transcript: Video,
  contract: FileSignature,
  invoice: FileText,
  receipt: Receipt,
  brief: FileText,
};

const DOC_BADGE: Record<string, string> = {
  transcript: 'bg-violet-100 text-violet-700',
  contract: 'bg-blue-100 text-blue-700',
  invoice: 'bg-amber-100 text-amber-700',
  receipt: 'bg-amber-100 text-amber-700',
  brief: 'bg-emerald-100 text-emerald-700',
};

export function DriveView({ docs }: { docs: DriveDoc[] }) {
  const router = useRouter();
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  async function sync() {
    setSyncing(true);
    setMsg(null);
    try {
      const res = await authedFetch('/api/drive/sync', { method: 'POST' });
      if (!res.ok) throw new Error();
      setMsg({ text: 'Scanning your Drive — new files appear here in a few seconds.', ok: true });
      setTimeout(() => router.refresh(), 4000);
    } catch {
      setMsg({ text: 'Could not start the scan. Connect Google in Settings first.', ok: false });
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-gray-500">
          {docs.length} file{docs.length !== 1 ? 's' : ''} processed
        </p>
        <button
          onClick={sync}
          disabled={syncing}
          className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
        >
          {syncing ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Scan Drive
        </button>
      </div>

      {msg && (
        <div className={`rounded-lg px-4 py-3 text-sm ${msg.ok ? 'bg-blue-50 text-blue-800' : 'bg-red-50 text-red-700'}`}>
          {msg.text}
        </div>
      )}

      {docs.length === 0 ? (
        <Card className="p-8 text-center">
          <HardDrive className="mx-auto text-gray-300" size={28} />
          <p className="mt-3 text-sm font-medium text-gray-500">No Drive files processed yet</p>
          <p className="mt-1 text-xs text-gray-400">
            Connect Google in Settings, then click <span className="font-medium">Scan Drive</span>. Kora finds
            meeting transcripts (last 30 days) and routes documents automatically.
          </p>
        </Card>
      ) : (
        <Card className="divide-y divide-gray-100">
          {docs.map((d) => {
            const Icon = DOC_ICON[d.docType ?? ''] ?? File;
            return (
              <div key={d.driveFileId} className="flex items-center gap-3 px-5 py-3">
                <Icon size={16} className="shrink-0 text-gray-400" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-gray-800">{d.fileName ?? 'Untitled'}</p>
                  <p className="mt-0.5 text-xs text-gray-400">{d.processedAt && formatDate(d.processedAt)}</p>
                </div>
                {d.docType && (
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize ${DOC_BADGE[d.docType] ?? 'bg-gray-100 text-gray-600'}`}>
                    {d.docType}
                  </span>
                )}
                {d.meetingId && (
                  <Link href="/butler/meetings" className="shrink-0 text-xs font-medium text-kora-600 hover:underline">
                    View meeting →
                  </Link>
                )}
              </div>
            );
          })}
        </Card>
      )}
    </div>
  );
}
