'use client';

/**
 * Choose which Drive folder Kora watches.
 *
 * `sync_drive_intel` only scans the folder recorded in
 * `google_connections.kora_folder_id` (plus Meet transcripts). Nothing in the
 * product ever set that column, so the folder branch was dead for every user and
 * documents added to Drive were never ingested. This is the control that sets it.
 *
 * It's a picker rather than "create a Kora folder for me" because the app holds
 * `drive.readonly`, which can list folders but cannot create one — auto-creating
 * would force every user to re-consent to a write scope.
 */

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { FolderOpen, Check, Loader2, RefreshCw } from 'lucide-react';
import { Card } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';

type DriveFolder = { id: string; name: string; selected: boolean };

export function FolderPicker() {
  const router = useRouter();
  const [folders, setFolders] = useState<DriveFolder[] | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await authedFetch('/api/drive/folders');
      if (!res.ok) throw new Error(await res.text());
      setFolders(await res.json());
    } catch {
      // The commonest cause by far is Google not being connected yet; say that
      // rather than showing a raw error the user can do nothing with.
      setError('Could not list your Drive folders. Is Google connected in Settings?');
      setFolders([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function choose(folderId: string | null) {
    setSaving(folderId ?? 'none');
    setError(null);
    try {
      const res = await authedFetch('/api/drive/folder', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folderId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? 'Could not save that folder');
      }
      setFolders((prev) => prev?.map((f) => ({ ...f, selected: f.id === folderId })) ?? null);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that folder');
    } finally {
      setSaving(null);
    }
  }

  const selected = folders?.find((f) => f.selected);

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
            <FolderOpen className="h-4 w-4" aria-hidden />
            Watched folder
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            {selected ? (
              <>
                Kora reads documents you put in <strong>{selected.name}</strong> and its subfolders.
              </>
            ) : (
              <>Pick a folder. Until you do, Kora only picks up Meet transcripts.</>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="shrink-0 rounded-md p-2 text-gray-400 hover:bg-gray-50 hover:text-gray-600"
          aria-label="Reload folder list"
        >
          <RefreshCw className="h-4 w-4" aria-hidden />
        </button>
      </div>

      {error && <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {folders === null ? (
        <p className="mt-4 flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          Loading your Drive folders…
        </p>
      ) : folders.length === 0 && !error ? (
        <p className="mt-4 text-sm text-gray-500">No folders found in your Drive.</p>
      ) : (
        <ul className="mt-4 max-h-72 space-y-1 overflow-y-auto">
          {folders.map((f) => (
            <li key={f.id}>
              <button
                type="button"
                onClick={() => void choose(f.selected ? null : f.id)}
                disabled={saving !== null}
                className={`flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition ${
                  f.selected ? 'bg-emerald-50 text-emerald-900' : 'text-gray-700 hover:bg-gray-50'
                } disabled:opacity-50`}
              >
                <span className="truncate">{f.name}</span>
                {saving === f.id ? (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-gray-400" aria-hidden />
                ) : f.selected ? (
                  <span className="flex shrink-0 items-center gap-1 text-xs font-medium">
                    <Check className="h-4 w-4" aria-hidden />
                    Watching
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
