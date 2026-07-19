'use client';

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { UploadCloud, Loader2, Download } from 'lucide-react';
import { authedFetch } from '@/lib/api/browser';

interface UploadResult {
  inserted: number;
  duplicatesSkipped: number;
  lowConfidence: number;
  avgConfidence: number;
  reconciled: number;
  rowsParsed: number;
}

export function UploadZone() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await authedFetch('/api/bookkeeping/upload', { method: 'POST', body: fd });
      const json = await res.json();
      if (!res.ok) {
        setError(typeof json.detail === 'string' ? json.detail : json.error ?? 'Upload failed');
      } else {
        setResult(json);
        router.refresh();
      }
    } catch (e: any) {
      setError(e?.message ?? 'Upload failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) upload(file);
        }}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragging ? 'border-kora-500 bg-kora-50' : 'border-gray-300 bg-white hover:border-kora-400'
        }`}
      >
        {busy ? (
          <Loader2 className="animate-spin text-kora-600" size={28} />
        ) : (
          <UploadCloud className="text-kora-600" size={28} />
        )}
        <p className="mt-3 text-sm font-medium text-gray-900">
          {busy ? 'AI is categorizing your transactions…' : 'Drop a bank statement CSV here'}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          Columns: Date, Description, Amount, Type (or Debit/Credit). Max 5MB.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload(file);
          }}
        />
      </div>

      <div className="mt-3 flex items-center gap-3">
        <a
          href="/sample-transactions.csv"
          download
          className="inline-flex items-center gap-1.5 text-xs font-medium text-kora-600 hover:underline"
        >
          <Download size={13} /> Download a sample CSV
        </a>
      </div>

      {error && (
        <div className="mt-3 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}
      {result && (
        <div className="mt-3 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          Imported <strong>{result.inserted}</strong> transactions
          {result.duplicatesSkipped > 0 && ` (${result.duplicatesSkipped} duplicates skipped)`}. AI
          categorized them at {Math.round(result.avgConfidence * 100)}% average confidence
          {result.lowConfidence > 0 && `, ${result.lowConfidence} flagged for review`}.
          {result.reconciled > 0 && (
            <span className="mt-1 block font-medium text-emerald-900">
              Matched {result.reconciled} incoming payment{result.reconciled > 1 ? 's' : ''} to open
              invoice{result.reconciled > 1 ? 's' : ''} — marked paid and stopped follow-ups.
            </span>
          )}
        </div>
      )}
    </div>
  );
}
