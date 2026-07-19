# Kora — frontend (Next.js 14)

Thin client for the Kora MVP. All data and AI live in the FastAPI backend; this app
fetches over HTTP (React Server Components via `lib/api/server.ts`, client actions via
`NEXT_PUBLIC_API_URL`).

```bash
npm install
npm run dev          # http://localhost:3000  (needs the backend running on :8000)
```

See the top-level [`../README.md`](../README.md) for the full architecture, the backend
setup, and the end-to-end demo flow. Configure the backend URL in `.env.local`
(`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`).
