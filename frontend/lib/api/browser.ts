'use client';

import { PUBLIC_API_BASE } from './config';
import { getSupabaseBrowser } from '@/lib/supabase/client';

async function authHeaders(extra?: HeadersInit): Promise<HeadersInit> {
  const supabase = getSupabaseBrowser();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return { ...(extra ?? {}), Authorization: `Bearer ${session?.access_token ?? ''}` };
}

// Authenticated fetch for client components — attaches the Supabase JWT.
export async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
  const headers = await authHeaders(init?.headers);
  return fetch(`${PUBLIC_API_BASE}${path}`, { ...init, headers });
}

// Authenticated file download (GET) — <a href> can't carry an auth header, so
// we fetch as a blob with the JWT and trigger a save.
export async function downloadAuthed(path: string, fallbackName = 'download'): Promise<void> {
  const res = await authedFetch(path);
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const disposition = res.headers.get('content-disposition') ?? '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const name = match?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
