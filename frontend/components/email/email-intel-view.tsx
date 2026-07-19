'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { RefreshCw, Mail, AlertTriangle, Clock, Send, X, ChevronDown, ChevronUp } from 'lucide-react';
import { Card, CardHeader } from '@/components/ui';
import { FormattedText } from '@/components/formatted-text';
import { authedFetch } from '@/lib/api/browser';
import { cn } from '@/lib/utils';
import type { EmailIntel } from '@/lib/api/types';

interface Props {
  intel: EmailIntel[];
}

interface Draft {
  subject: string;
  bodyText: string;
  bodyHtml: string;
}

const HEALTH_BADGE: Record<string, string> = {
  healthy: 'bg-emerald-100 text-emerald-700',
  good: 'bg-emerald-100 text-emerald-700',
  at_risk: 'bg-amber-100 text-amber-700',
  cooling: 'bg-orange-100 text-orange-700',
  critical: 'bg-red-100 text-red-700',
};

const SENTIMENT_CHIP: Record<string, string> = {
  positive: 'bg-emerald-50 text-emerald-700',
  neutral: 'bg-gray-100 text-gray-600',
  cautious: 'bg-amber-50 text-amber-700',
  concerning: 'bg-red-50 text-red-700',
};

export function EmailIntelView({ intel }: Props) {
  const router = useRouter();
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [draftClientId, setDraftClientId] = useState<string | null>(null);
  const [draftContext, setDraftContext] = useState('follow up');
  const [draftTone, setDraftTone] = useState('professional');
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);

  const sorted = [...intel].sort((a, b) => {
    if (a.actionNeeded && !b.actionNeeded) return -1;
    if (!a.actionNeeded && b.actionNeeded) return 1;
    return a.lastContactDays - b.lastContactDays;
  });

  async function syncGmail() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      await authedFetch('/api/gmail/sync', { method: 'POST' });
      setSyncMsg('Syncing in background — results update within a few minutes. Refresh to see latest.');
      router.refresh();
    } catch {
      setSyncMsg('Sync failed. Try again.');
    } finally {
      setSyncing(false);
    }
  }

  function openDraftModal(clientId: string) {
    setDraftClientId(clientId);
    setDraft(null);
    setDraftError(null);
    setDraftContext('follow up');
    setDraftTone('professional');
  }

  async function generateDraft() {
    if (!draftClientId) return;
    setDrafting(true);
    setDraftError(null);
    try {
      const res = await authedFetch(`/api/gmail/draft/${draftClientId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ context: draftContext, tone: draftTone }),
      });
      if (!res.ok) throw new Error('Draft generation failed');
      const data = await res.json();
      setDraft(data);
    } catch (err: unknown) {
      setDraftError(err instanceof Error ? err.message : 'Failed to generate draft');
    } finally {
      setDrafting(false);
    }
  }

  const draftClient = intel.find((i) => i.clientId === draftClientId);

  return (
    <div className="space-y-6">
      {/* Action bar */}
      <div className="flex items-center gap-3">
        <button
          onClick={syncGmail}
          disabled={syncing}
          className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw size={14} className={cn(syncing && 'animate-spin')} />
          {syncing ? 'Syncing…' : 'Sync Gmail'}
        </button>
        <span className="text-xs text-gray-400">Results are cached for 24 hours</span>
      </div>

      {syncMsg && (
        <div className="rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-800">{syncMsg}</div>
      )}

      {sorted.length === 0 ? (
        <Card>
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Mail size={30} className="text-gray-300" />
            <p className="mt-3 text-sm font-semibold text-gray-700">No email intel yet</p>
            <p className="mt-1 text-xs text-gray-500 max-w-xs">
              Click &ldquo;Sync Gmail&rdquo; to analyse your email threads. Kora needs Google connected and active clients with email addresses.
            </p>
          </div>
        </Card>
      ) : (
        <div className="space-y-4">
          {sorted.map((item) => {
            const isExpanded = expandedId === item.clientId;
            const healthKey = item.relationshipHealth?.toLowerCase().replace(/\s/g, '_') ?? '';
            const sentimentKey = item.sentiment?.toLowerCase() ?? '';

            return (
              <Card key={item.clientId}>
                <div className="px-5 py-4">
                  {/* Header */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="text-sm font-semibold text-gray-900">{item.clientName}</p>
                      <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', HEALTH_BADGE[healthKey] ?? 'bg-gray-100 text-gray-600')}>
                        {item.relationshipHealth}
                      </span>
                      {item.sentiment && (
                        <span className={cn('rounded-full px-2 py-0.5 text-xs', SENTIMENT_CHIP[sentimentKey] ?? 'bg-gray-100 text-gray-600')}>
                          {item.sentiment}
                        </span>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-1 text-xs text-gray-400">
                      <Clock size={12} />
                      {item.lastContactDays === 0 ? 'Today' : `${item.lastContactDays}d ago`}
                      {item.lastContactDirection && <span className="ml-1 text-gray-300">({item.lastContactDirection})</span>}
                    </div>
                  </div>

                  {/* Summary */}
                  {item.summary && (
                    <FormattedText text={item.summary} className="mt-2 text-sm text-gray-600" />
                  )}

                  {/* Action needed alert */}
                  {item.actionNeeded && (
                    <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2.5 text-sm text-amber-800">
                      <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                      <span>{item.actionDescription ?? 'Action required'}</span>
                    </div>
                  )}

                  {/* Expandable commitments / questions */}
                  {(item.commitmentsPending?.length > 0 || item.openQuestions?.length > 0) && (
                    <button
                      onClick={() => setExpandedId(isExpanded ? null : item.clientId)}
                      className="mt-3 flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-800"
                    >
                      {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      {isExpanded ? 'Hide details' : 'Show commitments & questions'}
                    </button>
                  )}

                  {isExpanded && (
                    <div className="mt-3 space-y-3">
                      {item.commitmentsPending?.length > 0 && (
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Pending commitments</p>
                          <ul className="space-y-1">
                            {(item.commitmentsPending as Array<Record<string, unknown>>).map((c, i) => (
                              <li key={i} className="text-xs text-gray-700 flex gap-1">
                                <span className="text-gray-400">·</span>
                                {String(c.what ?? c.description ?? JSON.stringify(c))}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {item.openQuestions?.length > 0 && (
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Open questions</p>
                          <ul className="space-y-1">
                            {(item.openQuestions as unknown[]).map((q, i) => (
                              <li key={i} className="text-xs text-gray-700 flex gap-1">
                                <span className="text-gray-400">·</span>
                                {String(q)}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Footer */}
                  <div className="mt-4 flex justify-end">
                    <button
                      onClick={() => openDraftModal(item.clientId)}
                      className="flex items-center gap-2 rounded-lg bg-kora-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-kora-700"
                    >
                      <Send size={12} /> Draft follow-up
                    </button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Draft modal */}
      {draftClientId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-gray-900">
                Draft email — {draftClient?.clientName}
              </h3>
              <button onClick={() => setDraftClientId(null)} className="text-gray-400 hover:text-gray-600">
                <X size={18} />
              </button>
            </div>

            {!draft ? (
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Purpose / context</label>
                  <textarea
                    rows={3}
                    value={draftContext}
                    onChange={(e) => setDraftContext(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                    placeholder="e.g. follow up on invoice, check in on project status"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Tone</label>
                  <select
                    value={draftTone}
                    onChange={(e) => setDraftTone(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                  >
                    <option value="professional">Professional</option>
                    <option value="friendly">Friendly</option>
                    <option value="firm">Firm</option>
                  </select>
                </div>
                {draftError && (
                  <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{draftError}</div>
                )}
                <div className="flex justify-end gap-2">
                  <button onClick={() => setDraftClientId(null)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
                    Cancel
                  </button>
                  <button
                    onClick={generateDraft}
                    disabled={drafting}
                    className="flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-50"
                  >
                    {drafting ? 'Generating…' : 'Generate draft'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                  <p className="text-xs font-semibold text-gray-500 mb-1">Subject</p>
                  <p className="text-sm font-medium text-gray-900">{draft.subject}</p>
                </div>
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                  <p className="text-xs font-semibold text-gray-500 mb-1">Body</p>
                  <p className="whitespace-pre-wrap text-sm text-gray-700">{draft.bodyText}</p>
                </div>
                <div className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                  This draft has been queued for your approval in the Manager page.
                </div>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setDraft(null)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
                    Regenerate
                  </button>
                  <button onClick={() => setDraftClientId(null)} className="rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700">
                    Done
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
