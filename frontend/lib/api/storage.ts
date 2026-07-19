'use client';

import { authedFetch } from './browser';

// Storage helpers (artifacts/gcp-cloud.md §6). The frontend never builds GCS
// paths or talks to GCS directly — it asks the backend for a short-lived signed
// URL (when storage is configured) and opens it. The agent-log export also works
// with storage OFF: the backend streams the CSV inline, which we save as a blob.

export async function isStorageConfigured(): Promise<boolean> {
  try {
    const res = await authedFetch('/api/storage/status');
    if (!res.ok) return false;
    return Boolean((await res.json()).configured);
  } catch {
    return false;
  }
}

// Download the agent-log CSV. Handles both response shapes:
//  - storage ON  → JSON { url } (signed URL) → open in a new tab
//  - storage OFF → text/csv body → save as a blob
export async function downloadAgentLogExport(): Promise<void> {
  const res = await authedFetch('/api/storage/exports/agent-log');
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const ct = res.headers.get('content-type') ?? '';
  if (ct.includes('application/json')) {
    const { url } = (await res.json()) as { url: string };
    window.open(url, '_blank');
    return;
  }
  const blob = await res.blob();
  const disposition = res.headers.get('content-disposition') ?? '';
  const name = disposition.match(/filename="?([^"]+)"?/)?.[1] ?? 'kora-agent-log.csv';
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

// Receipt upload (requires storage configured — backend returns 503 otherwise).
export async function uploadReceipt(transactionId: string, file: File): Promise<{ path: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await authedFetch(`/api/storage/receipts/${transactionId}`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error(typeof j.detail === 'string' ? j.detail : 'Upload failed');
  }
  return res.json();
}

// Open a previously uploaded receipt via a short-lived signed URL.
export async function openReceipt(transactionId: string): Promise<void> {
  const res = await authedFetch(`/api/storage/receipts/${transactionId}`);
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error(typeof j.detail === 'string' ? j.detail : 'No receipt found');
  }
  const { url } = (await res.json()) as { url: string };
  window.open(url, '_blank');
}
