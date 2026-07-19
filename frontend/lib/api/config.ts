// Single source of truth for the FastAPI backend base URL.
// - Server components / route handlers use API_BASE (can be an internal URL).
// - Client components use NEXT_PUBLIC_API_URL (must be browser-reachable).
export const API_BASE =
  process.env.KORA_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export const PUBLIC_API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
