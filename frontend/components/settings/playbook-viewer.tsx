'use client';

import { useState } from 'react';
import type { PlaybookEntry, PlaybookStats } from '@/lib/api/types';
import { authedFetch } from '@/lib/api/browser';

async function apiFetch<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await authedFetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} failed (${res.status})`);
  if (res.status === 204) return undefined as T;
  return res.json();
}

type Category = PlaybookEntry['category'] | 'all';

const CATEGORY_LABELS: Record<string, string> = {
  all: 'All',
  correction: 'Corrections',
  user_preference: 'Preferences',
  client_intelligence: 'Client intel',
  business_pattern: 'Patterns',
  business_rule: 'Rules',
  extracted_fact: 'Facts',
};

const CATEGORY_BADGE: Record<string, string> = {
  correction: 'bg-red-100 text-red-700',
  user_preference: 'bg-blue-100 text-blue-700',
  client_intelligence: 'bg-purple-100 text-purple-700',
  business_pattern: 'bg-teal-100 text-teal-700',
  business_rule: 'bg-amber-100 text-amber-700',
  extracted_fact: 'bg-gray-100 text-gray-700',
};

function ConfidenceDot({ confidence }: { confidence: number }) {
  const color =
    confidence >= 0.7 ? 'bg-green-500' : confidence >= 0.5 ? 'bg-amber-400' : 'bg-gray-300';
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${color} flex-shrink-0`} title={`Confidence: ${Math.round(confidence * 100)}%`} />;
}

interface Props {
  entries: PlaybookEntry[];
  stats: PlaybookStats;
}

export function PlaybookViewer({ entries: initialEntries, stats: initialStats }: Props) {
  const [entries, setEntries] = useState(initialEntries);
  const [stats, setStats] = useState(initialStats);
  const [activeTab, setActiveTab] = useState<Category>('all');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editSummary, setEditSummary] = useState('');
  const [editConfidence, setEditConfidence] = useState(0.5);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [compressing, setCompressing] = useState(false);

  const filtered =
    activeTab === 'all' ? entries : entries.filter((e) => e.category === activeTab);

  function openEdit(entry: PlaybookEntry) {
    setEditingId(entry.id);
    setEditSummary(entry.summary ?? '');
    setEditConfidence(entry.confidence);
  }

  async function saveEdit() {
    if (!editingId) return;
    try {
      const updated = await apiFetch<PlaybookEntry>(`/api/playbook/${editingId}`, 'PATCH', {
        summary: editSummary || null,
        confidence: editConfidence,
      });
      setEntries((prev) => prev.map((e) => (e.id === editingId ? updated : e)));
      setEditingId(null);
    } catch {
      alert('Failed to save');
    }
  }

  async function confirmDelete() {
    if (!deletingId) return;
    try {
      await apiFetch(`/api/playbook/${deletingId}`, 'DELETE');
      setEntries((prev) => prev.filter((e) => e.id !== deletingId));
      setStats((s) => ({ ...s, total: s.total - 1 }));
      setDeletingId(null);
    } catch {
      alert('Failed to delete');
    }
  }

  async function detectPatterns() {
    setDetecting(true);
    try {
      const res = await apiFetch<{ detected: number }>('/api/playbook/detect', 'POST', {});
      const refreshed = await apiFetch<PlaybookEntry[]>('/api/playbook', 'GET');
      setEntries(refreshed);
      alert(`Detected ${res.detected} new pattern(s).`);
    } catch {
      alert('Pattern detection failed');
    } finally {
      setDetecting(false);
    }
  }

  async function refreshMemory() {
    setCompressing(true);
    try {
      await apiFetch('/api/playbook/compress', 'POST', {});
    } catch {
      alert('Memory refresh failed');
    } finally {
      setCompressing(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Stats header */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Total learned" value={stats.total} />
        <StatCard label="Corrections" value={stats.corrections} />
        <StatCard label="High confidence" value={stats.highConfidence} />
        <StatCard label="Patterns" value={stats.patterns} />
      </div>

      {/* Action buttons */}
      <div className="flex gap-3">
        <button
          onClick={detectPatterns}
          disabled={detecting}
          className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          {detecting ? 'Detecting…' : 'Detect patterns'}
        </button>
        <button
          onClick={refreshMemory}
          disabled={compressing}
          className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          {compressing ? 'Refreshing…' : 'Refresh memory'}
        </button>
      </div>

      {/* Category tabs */}
      <div className="flex flex-wrap gap-2 border-b border-gray-200">
        {(Object.keys(CATEGORY_LABELS) as Category[]).map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveTab(cat)}
            className={`px-3 py-1.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === cat
                ? 'border-kora-600 text-kora-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {CATEGORY_LABELS[cat]}
          </button>
        ))}
      </div>

      {/* Entry list */}
      {filtered.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-3">
          {filtered.map((entry) => (
            <div key={entry.id} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
              <div className="flex items-start gap-3">
                <ConfidenceDot confidence={entry.confidence} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${CATEGORY_BADGE[entry.category] ?? 'bg-gray-100 text-gray-700'}`}>
                      {CATEGORY_LABELS[entry.category] ?? entry.category}
                    </span>
                    <span className="text-sm font-semibold text-gray-800 truncate">{entry.key}</span>
                  </div>
                  {entry.summary && (
                    <p className="mt-1 text-sm text-gray-600">{entry.summary}</p>
                  )}
                  <p className="mt-1 text-xs text-gray-400">
                    Observed {entry.observationCount}× · {entry.lastObservedAt ? new Date(entry.lastObservedAt).toLocaleDateString() : 'unknown date'}
                  </p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <button
                    onClick={() => openEdit(entry)}
                    className="text-xs text-gray-400 hover:text-gray-700"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => setDeletingId(entry.id)}
                    className="text-xs text-red-400 hover:text-red-600"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Edit modal */}
      {editingId && (
        <Modal title="Edit entry" onClose={() => setEditingId(null)}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Summary</label>
              <textarea
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
                rows={3}
                value={editSummary}
                onChange={(e) => setEditSummary(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Confidence: {Math.round(editConfidence * 100)}%
              </label>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={editConfidence}
                onChange={(e) => setEditConfidence(Number(e.target.value))}
                className="w-full"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setEditingId(null)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
              <button onClick={saveEdit} className="rounded-lg bg-kora-600 px-4 py-2 text-sm font-medium text-white hover:bg-kora-700">Save</button>
            </div>
          </div>
        </Modal>
      )}

      {/* Delete confirmation */}
      {deletingId && (
        <Modal title="Delete entry?" onClose={() => setDeletingId(null)}>
          <p className="text-sm text-gray-600">Kora will forget this learning. This cannot be undone.</p>
          <div className="mt-4 flex justify-end gap-2">
            <button onClick={() => setDeletingId(null)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
            <button onClick={confirmDelete} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700">Delete</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-sm text-gray-500">{label}</p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <svg className="w-12 h-12 text-gray-300 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
      <p className="text-sm font-medium text-gray-500">Nothing learned yet</p>
      <p className="text-xs text-gray-400 mt-1">Kora will start learning as you approve tasks, correct categories, and interact with clients.</p>
    </div>
  );
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}
