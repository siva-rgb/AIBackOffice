'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import {
  Video, FileText, Upload, RefreshCw, ChevronDown, ChevronUp,
  CheckSquare, Square, AlertTriangle, Clock, User, Mail, Loader2
} from 'lucide-react';
import { Card, CardHeader } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import { cn } from '@/lib/utils';
import type { Meeting, MeetingActionItem, Client } from '@/lib/api/types';

interface Props {
  meetings: Meeting[];
}

type Tab = 'list' | 'tasks' | 'upload';

interface OpenActionItem extends MeetingActionItem {
  meetingId: string;
  meetings: { title: string; meetingDate: string; clientId: string | null; clients: { name: string } | null } | null;
}

const PARSE_STATUS_BADGE: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-600',
  parsed: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
  partial: 'bg-amber-100 text-amber-700',
};

const SENTIMENT_CHIP: Record<string, string> = {
  positive: 'text-emerald-600',
  neutral: 'text-gray-500',
  cautious: 'text-amber-600',
  concerning: 'text-red-600',
};

const PRIORITY_COLOR: Record<string, string> = {
  high: 'text-red-600',
  medium: 'text-amber-600',
  low: 'text-gray-400',
};

export function MeetingsView({ meetings: initialMeetings }: Props) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<Tab>('list');
  const [meetings, setMeetings] = useState(initialMeetings);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [processingBanner, setProcessingBanner] = useState(false);
  const [followupBusy, setFollowupBusy] = useState<string | null>(null);
  const [followupMsg, setFollowupMsg] = useState<{ id: string; text: string; ok: boolean } | null>(null);
  const [tasks, setTasks] = useState<OpenActionItem[] | null>(null);

  useEffect(() => {
    if (activeTab !== 'tasks' || tasks !== null) return;
    authedFetch('/api/meetings/action-items?status=open')
      .then((r) => r.json())
      .then((data) => setTasks(Array.isArray(data) ? data : []))
      .catch(() => setTasks([]));
  }, [activeTab, tasks]);

  async function completeTask(t: OpenActionItem) {
    setTasks((prev) => (prev ? prev.filter((x) => x.id !== t.id) : prev));
    try {
      await authedFetch(`/api/meetings/${t.meetingId}/action-items/${t.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ status: 'done' }),
      });
    } catch {
      setTasks((prev) => (prev ? [t, ...prev] : prev)); // rollback on failure
    }
  }

  async function draftFollowup(meetingId: string) {
    setFollowupBusy(meetingId);
    setFollowupMsg(null);
    try {
      const res = await authedFetch(`/api/meetings/${meetingId}/followup`, { method: 'POST' });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setFollowupMsg({ id: meetingId, text: typeof json.detail === 'string' ? json.detail : 'Could not draft follow-up', ok: false });
      } else {
        setFollowupMsg({ id: meetingId, text: `Follow-up drafted for ${json.client ?? 'the client'} — approve it in Business Manager to send.`, ok: true });
      }
    } catch (e: any) {
      setFollowupMsg({ id: meetingId, text: e?.message ?? 'Could not draft follow-up', ok: false });
    } finally {
      setFollowupBusy(null);
    }
  }

  // Upload tab state
  const [clients, setClients] = useState<Client[]>([]);
  const [uploadMode, setUploadMode] = useState<'file' | 'note'>('file');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Quick note form
  const [noteTitle, setNoteTitle] = useState('');
  const [noteText, setNoteText] = useState('');
  const [noteClientId, setNoteClientId] = useState('');
  const [noteDate, setNoteDate] = useState(() =>
    new Date().toISOString().slice(0, 16)
  );

  // File upload form
  const [fileTitle, setFileTitle] = useState('');
  const [fileClientId, setFileClientId] = useState('');
  const [fileDate, setFileDate] = useState(() =>
    new Date().toISOString().slice(0, 16)
  );

  useEffect(() => {
    authedFetch('/api/clients', { method: 'GET' })
      .then((r) => r.json())
      .then((data: Client[]) => setClients(data))
      .catch(() => {});
  }, []);

  async function refresh() {
    setRefreshing(true);
    try {
      const res = await authedFetch('/api/meetings', { method: 'GET' });
      const data: Meeting[] = await res.json();
      setMeetings(data);
    } catch {
      // silently fail
    } finally {
      setRefreshing(false);
    }
  }

  async function toggleActionItem(meetingId: string, item: MeetingActionItem) {
    const newStatus = item.status === 'done' ? 'open' : 'done';
    try {
      await authedFetch(`/api/meetings/${meetingId}/action-items/${item.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
      setMeetings((prev) =>
        prev.map((m) =>
          m.id === meetingId
            ? {
                ...m,
                meetingActionItems: m.meetingActionItems.map((ai) =>
                  ai.id === item.id ? { ...ai, status: newStatus } : ai
                ),
              }
            : m
        )
      );
    } catch {
      // silently fail
    }
  }

  async function submitQuickNote(e: React.FormEvent) {
    e.preventDefault();
    setUploading(true);
    setUploadError(null);
    try {
      const res = await authedFetch('/api/meetings/quick-note', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notes: noteText,
          title: noteTitle || 'Meeting note',
          clientId: noteClientId || null,
          meetingDate: new Date(noteDate).toISOString(),
        }),
      });
      if (!res.ok) throw new Error('Submission failed');
      setNoteTitle('');
      setNoteText('');
      setNoteClientId('');
      setProcessingBanner(true);
      setActiveTab('list');
      await refresh();
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : 'Submission failed');
    } finally {
      setUploading(false);
    }
  }

  async function submitFileUpload(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) { setUploadError('Select a file first'); return; }
    if (file.size > 2 * 1024 * 1024) { setUploadError('File must be under 2 MB'); return; }

    setUploading(true);
    setUploadError(null);
    try {
      // Step 1: create meeting record
      const createRes = await authedFetch('/api/meetings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: fileTitle || file.name.replace(/\.[^.]+$/, ''),
          meetingDate: new Date(fileDate).toISOString(),
          clientId: fileClientId || null,
          meetingType: 'call',
        }),
      });
      if (!createRes.ok) throw new Error('Failed to create meeting record');
      const created: Meeting = await createRes.json();

      // Step 2: upload transcript
      const formData = new FormData();
      formData.append('file', file);
      const uploadRes = await authedFetch(`/api/meetings/${created.id}/transcript`, {
        method: 'POST',
        body: formData,
      });
      if (!uploadRes.ok) throw new Error('Transcript upload failed');

      setFileTitle('');
      setFileClientId('');
      if (fileRef.current) fileRef.current.value = '';
      setProcessingBanner(true);
      setActiveTab('list');
      await refresh();
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {(['list', 'tasks', 'upload'] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === tab
                ? 'border-kora-600 text-kora-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            )}
          >
            {tab === 'list' ? 'Meetings' : tab === 'tasks' ? 'Tasks' : 'Upload transcript'}
          </button>
        ))}
      </div>

      {activeTab === 'list' && (
        <div className="space-y-4">
          {processingBanner && (
            <div className="flex items-center justify-between rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-800">
              <span>Processing in background — action items will appear shortly.</span>
              <button
                onClick={() => { setProcessingBanner(false); refresh(); }}
                className="ml-3 flex items-center gap-1 font-medium underline"
              >
                <RefreshCw size={13} /> Refresh
              </button>
            </div>
          )}

          <div className="flex justify-end">
            <button
              onClick={refresh}
              disabled={refreshing}
              className="flex items-center gap-2 rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
            >
              <RefreshCw size={13} className={cn(refreshing && 'animate-spin')} />
              Refresh
            </button>
          </div>

          {meetings.length === 0 ? (
            <Card>
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <Video size={30} className="text-gray-300" />
                <p className="mt-3 text-sm font-semibold text-gray-700">No meetings yet</p>
                <p className="mt-1 text-xs text-gray-500">
                  Upload a transcript or add a quick note to get started.
                </p>
                <button
                  onClick={() => setActiveTab('upload')}
                  className="mt-4 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700"
                >
                  Upload transcript
                </button>
              </div>
            </Card>
          ) : (
            <div className="space-y-3">
              {meetings.map((m) => {
                const isExpanded = expandedId === m.id;
                const statusKey = m.parseStatus ?? 'pending';

                return (
                  <Card key={m.id}>
                    <div className="px-5 py-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-sm font-semibold text-gray-900">{m.title}</p>
                            <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', PARSE_STATUS_BADGE[statusKey] ?? 'bg-gray-100 text-gray-600')}>
                              {statusKey}
                            </span>
                            {m.meetingType && (
                              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                                {m.meetingType}
                              </span>
                            )}
                          </div>
                          <div className="mt-0.5 flex flex-wrap items-center gap-3 text-xs text-gray-500">
                            <span className="flex items-center gap-1">
                              <Clock size={11} />
                              {new Date(m.meetingDate).toLocaleDateString()}
                            </span>
                            {m.clients?.name && (
                              <span className="flex items-center gap-1">
                                <User size={11} /> {m.clients.name}
                              </span>
                            )}
                            {m.sentiment && m.parseStatus === 'parsed' && (
                              <span className={cn('font-medium', SENTIMENT_CHIP[m.sentiment] ?? 'text-gray-500')}>
                                {m.sentiment}
                              </span>
                            )}
                          </div>
                        </div>

                        {m.parseStatus === 'parsed' && (
                          <button
                            onClick={() => setExpandedId(isExpanded ? null : m.id)}
                            className="shrink-0 flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800"
                          >
                            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            {isExpanded ? 'Hide' : 'Details'}
                          </button>
                        )}
                      </div>

                      {/* Expanded details */}
                      {isExpanded && m.parseStatus === 'parsed' && (
                        <div className="mt-4 space-y-4 border-t border-gray-100 pt-4">
                          {m.summary && (
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Summary</p>
                              <p className="text-sm text-gray-700">{m.summary}</p>
                            </div>
                          )}

                          {m.risksFlagged?.length > 0 && (
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Risks</p>
                              <ul className="space-y-1">
                                {m.risksFlagged.map((r, i) => (
                                  <li key={i} className="flex items-start gap-2 text-xs text-gray-700">
                                    <AlertTriangle size={12} className={cn('mt-0.5 shrink-0', r.severity === 'high' ? 'text-red-500' : r.severity === 'medium' ? 'text-amber-500' : 'text-gray-400')} />
                                    {r.risk}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {m.commitments?.length > 0 && (
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Commitments</p>
                              <ul className="space-y-1">
                                {m.commitments.map((c, i) => (
                                  <li key={i} className="text-xs text-gray-700">
                                    <span className="font-medium">{c.who}:</span> {c.what}
                                    {c.byWhen && <span className="text-gray-400"> · by {c.byWhen}</span>}
                                    {c.amount && <span className="text-gray-400"> · {c.amount}</span>}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {m.meetingActionItems?.length > 0 && (
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Action items</p>
                              <ul className="space-y-2">
                                {m.meetingActionItems.map((ai) => (
                                  <li key={ai.id} className="flex items-start gap-2">
                                    <button
                                      onClick={() => toggleActionItem(m.id, ai)}
                                      className="mt-0.5 shrink-0 text-gray-400 hover:text-kora-600"
                                    >
                                      {ai.status === 'done' ? (
                                        <CheckSquare size={15} className="text-emerald-500" />
                                      ) : (
                                        <Square size={15} />
                                      )}
                                    </button>
                                    <div className="min-w-0 flex-1">
                                      <p className={cn('text-xs text-gray-700', ai.status === 'done' && 'line-through text-gray-400')}>
                                        {ai.description}
                                      </p>
                                      <p className="mt-0.5 text-xs text-gray-400">
                                        {ai.owner}
                                        {ai.dueDate && <> · {ai.dueDate}</>}
                                        {ai.priority && (
                                          <span className={cn('ml-1 font-medium', PRIORITY_COLOR[ai.priority] ?? 'text-gray-400')}>
                                            · {ai.priority}
                                          </span>
                                        )}
                                      </p>
                                    </div>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {/* Draft follow-up email */}
                          <div className="border-t border-gray-100 pt-3">
                            <button
                              onClick={() => draftFollowup(m.id)}
                              disabled={followupBusy === m.id}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-kora-200 bg-white px-3 py-1.5 text-xs font-semibold text-kora-700 hover:bg-kora-50 disabled:opacity-60"
                            >
                              {followupBusy === m.id ? <Loader2 size={13} className="animate-spin" /> : <Mail size={13} />}
                              Draft follow-up email
                            </button>
                            {followupMsg?.id === m.id && (
                              <p className={cn('mt-2 text-xs', followupMsg.ok ? 'text-emerald-600' : 'text-red-600')}>
                                {followupMsg.text}
                              </p>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      )}

      {activeTab === 'tasks' && (
        <div className="space-y-3">
          <p className="text-sm text-gray-500">Open action items across all meetings — check one off when it&apos;s done.</p>
          {tasks === null ? (
            <Card className="p-5 text-sm text-gray-400">Loading tasks…</Card>
          ) : tasks.length === 0 ? (
            <Card className="p-8 text-center">
              <CheckSquare className="mx-auto text-gray-300" size={26} />
              <p className="mt-3 text-sm font-medium text-gray-500">No open action items</p>
              <p className="mt-1 text-xs text-gray-400">Action items extracted from meetings show up here until you complete them.</p>
            </Card>
          ) : (
            <Card className="divide-y divide-gray-100">
              {tasks.map((t) => {
                const overdue = t.dueDate && t.dueDate < new Date().toISOString().slice(0, 10);
                return (
                  <div key={t.id} className="flex items-start gap-3 px-5 py-3">
                    <button onClick={() => completeTask(t)} className="mt-0.5 shrink-0 text-gray-300 hover:text-emerald-500" aria-label="Mark done">
                      <Square size={16} />
                    </button>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-gray-800">{t.description}</p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-gray-400">
                        <span className="capitalize">{t.owner}</span>
                        {t.meetings?.clients?.name && <>· {t.meetings.clients.name}</>}
                        {t.meetings?.title && <>· {t.meetings.title}</>}
                        {t.dueDate && <span className={cn(overdue && 'font-medium text-red-500')}>· due {t.dueDate}</span>}
                        {t.priority && <span className={cn('font-medium', PRIORITY_COLOR[t.priority] ?? 'text-gray-400')}>· {t.priority}</span>}
                      </p>
                    </div>
                  </div>
                );
              })}
            </Card>
          )}
        </div>
      )}

      {activeTab === 'upload' && (
        <div className="space-y-6">
          {/* Mode toggle */}
          <div className="flex gap-2">
            <button
              onClick={() => setUploadMode('file')}
              className={cn(
                'flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                uploadMode === 'file'
                  ? 'bg-kora-600 text-white'
                  : 'border border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
              )}
            >
              <Upload size={14} /> Upload file
            </button>
            <button
              onClick={() => setUploadMode('note')}
              className={cn(
                'flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                uploadMode === 'note'
                  ? 'bg-kora-600 text-white'
                  : 'border border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
              )}
            >
              <FileText size={14} /> Quick note
            </button>
          </div>

          {uploadMode === 'file' && (
            <Card>
              <CardHeader title="Upload transcript file" subtitle=".txt, .vtt, .srt, .pdf, .docx — max 2 MB" />
              <form onSubmit={submitFileUpload} className="space-y-4 px-5 py-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Transcript file *</label>
                  <input
                    ref={fileRef}
                    required
                    type="file"
                    accept=".txt,.vtt,.srt,.pdf,.docx"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 file:mr-3 file:rounded-md file:border-0 file:bg-kora-50 file:px-3 file:py-1 file:text-xs file:font-medium file:text-kora-700 hover:file:bg-kora-100"
                  />
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Meeting title</label>
                    <input
                      type="text"
                      value={fileTitle}
                      onChange={(e) => setFileTitle(e.target.value)}
                      placeholder="Optional — defaults to filename"
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Meeting date</label>
                    <input
                      type="datetime-local"
                      value={fileDate}
                      onChange={(e) => setFileDate(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Client</label>
                  <select
                    value={fileClientId}
                    onChange={(e) => setFileClientId(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                  >
                    <option value="">No specific client</option>
                    {clients.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
                {uploadError && (
                  <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{uploadError}</div>
                )}
                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={uploading}
                    className="flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-50"
                  >
                    <Upload size={14} />
                    {uploading ? 'Uploading…' : 'Upload & process'}
                  </button>
                </div>
              </form>
            </Card>
          )}

          {uploadMode === 'note' && (
            <Card>
              <CardHeader title="Quick meeting note" subtitle="Type or paste notes — Kora extracts action items automatically" />
              <form onSubmit={submitQuickNote} className="space-y-4 px-5 py-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Title</label>
                    <input
                      type="text"
                      value={noteTitle}
                      onChange={(e) => setNoteTitle(e.target.value)}
                      placeholder="Meeting note"
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Date</label>
                    <input
                      type="datetime-local"
                      value={noteDate}
                      onChange={(e) => setNoteDate(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Client</label>
                  <select
                    value={noteClientId}
                    onChange={(e) => setNoteClientId(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                  >
                    <option value="">No specific client</option>
                    {clients.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Notes *</label>
                  <textarea
                    required
                    rows={8}
                    value={noteText}
                    onChange={(e) => setNoteText(e.target.value)}
                    placeholder="Paste meeting notes, decisions, action items…"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                  />
                </div>
                {uploadError && (
                  <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{uploadError}</div>
                )}
                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={uploading}
                    className="flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-50"
                  >
                    <FileText size={14} />
                    {uploading ? 'Saving…' : 'Save & process'}
                  </button>
                </div>
              </form>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
