import { API_BASE } from './config';
import { getAccessToken } from '@/lib/supabase/server';

// Server-side fetch used by React Server Components. Forwards the logged-in
// user's Supabase access token to FastAPI (SKILL.md §3). Always no-store so
// dashboards reflect live state.
export async function serverGet<T>(path: string): Promise<T> {
  const token = await getAccessToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token ?? ''}` },
    cache: 'no-store',
  });
  if (!res.ok) {
    throw new Error(`Backend ${res.status} on GET ${path}`);
  }
  return res.json() as Promise<T>;
}
