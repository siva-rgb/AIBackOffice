'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { UploadCloud, FileText, Loader2, ScanSearch, ClipboardPaste, CheckCircle2, ArrowRight } from 'lucide-react';
import { Card } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import type { ContractReview, Client } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { ContractReviewView } from './contract-review';

type Mode = 'upload' | 'paste';

type SavedInfo = { contractId: string | null; clientId: string | null; engagementId: string | null; savedFile: boolean };
type ReviewResponse = ContractReview & { saved?: SavedInfo };

export function ContractReviewer() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<Mode>('upload');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<ContractReview | null>(null);
  const [saved, setSaved] = useState<SavedInfo | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [dragging, setDragging] = useState(false);

  // Butler linkage: which client is this contract from?
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState('');
  const [save, setSave] = useState(true);

  useEffect(() => {
    authedFetch('/api/clients')
      .then((r) => (r.ok ? r.json() : []))
      .then((cs) => setClients(Array.isArray(cs) ? cs : []))
      .catch(() => setClients([]));
  }, []);

  const selectedClient = clients.find((c) => c.id === clientId) ?? null;

  function applyResult(json: ReviewResponse) {
    setReview(json);
    setSaved(json.saved ?? null);
  }

  async function reviewUpload(file: File) {
    setBusy(true); setError(null); setReview(null); setSaved(null);
    setFileName(file.name);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('save', String(save));
      if (clientId) fd.append('clientId', clientId);
      const res = await authedFetch('/api/contracts/review/upload', { method: 'POST', body: fd });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Review failed');
      applyResult(json as ReviewResponse);
    } catch (e: any) {
      setError(e?.message ?? 'Review failed');
    } finally {
      setBusy(false);
    }
  }

  async function reviewText() {
    if (text.trim().length < 20) {
      setError('Please paste at least a paragraph of the contract.');
      return;
    }
    setBusy(true); setError(null); setReview(null); setSaved(null);
    try {
      const res = await authedFetch('/api/contracts/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, save, clientId: clientId || undefined }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Review failed');
      applyResult(json as ReviewResponse);
    } catch (e: any) {
      setError(e?.message ?? 'Review failed');
    } finally {
      setBusy(false);
    }
  }

  const tab = (m: Mode, label: string, Icon: typeof UploadCloud) => (
    <button
      onClick={() => { setMode(m); setError(null); }}
      className={cn(
        'inline-flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-medium',
        mode === m ? 'border-kora-600 text-kora-700' : 'border-transparent text-gray-500 hover:text-gray-700',
      )}
    >
      <Icon size={15} /> {label}
    </button>
  );

  const input =
    'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';

  return (
    <div className="space-y-6">
      {/* Butler linkage controls */}
      <Card className="p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Which client is this from?</label>
            <select className={input} value={clientId} onChange={(e) => setClientId(e.target.value)}>
              <option value="">Not linked to a client</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <p className="mt-1 text-xs text-gray-400">
              Linking lets your Butler track the contract and create an engagement for the work.
            </p>
          </div>
          <div className="flex items-end">
            <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-kora-600 focus:ring-kora-500" />
              Save this contract so the Butler knows about it
            </label>
          </div>
        </div>
      </Card>

      <Card>
        <div className="flex border-b border-gray-100 px-3">
          {tab('upload', 'Upload file', UploadCloud)}
          {tab('paste', 'Paste text', ClipboardPaste)}
        </div>

        <div className="p-5">
          {mode === 'upload' ? (
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault(); setDragging(false);
                const f = e.dataTransfer.files?.[0];
                if (f) reviewUpload(f);
              }}
              onClick={() => inputRef.current?.click()}
              className={cn(
                'flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors',
                dragging ? 'border-kora-500 bg-kora-50' : 'border-gray-300 bg-white hover:border-kora-400',
              )}
            >
              {busy ? <Loader2 className="animate-spin text-kora-600" size={28} /> : <FileText className="text-kora-600" size={28} />}
              <p className="mt-3 text-sm font-medium text-gray-900">
                {busy ? 'AI is reviewing the contract…' : 'Drop a contract here — PDF, Word, or text'}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {fileName ? fileName : 'A client just sent you an agreement? Let Kora flag the risks before you sign.'}
              </p>
              <input
                ref={inputRef}
                type="file"
                accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
                className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) reviewUpload(f); }}
              />
            </div>
          ) : (
            <>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={10}
                placeholder="Paste the full contract text here…"
                className="w-full rounded-lg border border-gray-300 p-3 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500"
              />
              <button
                onClick={reviewText}
                disabled={busy}
                className="mt-3 inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : <ScanSearch size={15} />}
                Review contract
              </button>
            </>
          )}

          {error && <div className="mt-3 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        </div>
      </Card>

      {saved?.contractId && (
        <div className="flex items-start gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            {selectedClient ? (
              <>
                Saved to your Butler and linked to <span className="font-semibold">{selectedClient.name}</span>
                {saved.engagementId && ' — an engagement was created to track the work'}.
                {' '}
                <Link href={`/butler/clients/${saved.clientId}`} className="inline-flex items-center gap-0.5 font-medium underline">
                  Open client <ArrowRight size={13} />
                </Link>
              </>
            ) : (
              <>Saved to your contracts. Tip: pick a client above to let the Butler track the deliverable.</>
            )}
            {!saved.savedFile && <span className="block text-xs text-emerald-700/80">(File copy not stored — storage isn’t configured; the text and review are saved.)</span>}
          </div>
        </div>
      )}

      {review && (
        <Card className="p-5">
          <ContractReviewView review={review} />
        </Card>
      )}
    </div>
  );
}
