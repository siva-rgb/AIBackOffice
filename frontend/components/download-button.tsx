'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { downloadAuthed } from '@/lib/api/browser';
import { cn } from '@/lib/utils';

// Authenticated file download — fetches with the Supabase JWT and saves the
// blob (a plain <a href> can't send an Authorization header).
export function DownloadButton({
  path,
  filename,
  children,
  className,
}: {
  path: string;
  filename: string;
  children: React.ReactNode;
  className?: string;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      onClick={async () => {
        setBusy(true);
        try {
          await downloadAuthed(path, filename);
        } finally {
          setBusy(false);
        }
      }}
      disabled={busy}
      className={cn('inline-flex items-center gap-2 disabled:opacity-60', className)}
    >
      {busy && <Loader2 size={14} className="animate-spin" />}
      {children}
    </button>
  );
}
