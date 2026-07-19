import { ServerCrash } from 'lucide-react';
import { Card } from '@/components/ui';
import { PUBLIC_API_BASE } from '@/lib/api/config';

// Shown when the FastAPI backend isn't reachable — the frontend is a thin
// client, so it needs the API running.
export function BackendDown() {
  return (
    <Card className="flex flex-col items-center justify-center py-16 text-center">
      <ServerCrash className="text-red-500" size={32} />
      <h2 className="mt-4 text-lg font-semibold text-gray-900">Backend not reachable</h2>
      <p className="mt-1 max-w-md text-sm text-gray-500">
        The Kora API ({PUBLIC_API_BASE}) isn&apos;t responding. Start it with{' '}
        <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs">uvicorn app.main:app</code> in{' '}
        <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs">backend/</code>, then refresh.
      </p>
    </Card>
  );
}
