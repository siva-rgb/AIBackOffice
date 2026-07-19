import { serverGet } from '@/lib/api/server';
import type { ManagerSnapshot } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { ManagerConsole } from '@/components/manager/manager-console';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Business Manager — Kora' };

export default async function ManagerPage() {
  let snapshot: ManagerSnapshot;
  try {
    snapshot = await serverGet<ManagerSnapshot>('/api/manager');
  } catch {
    return <BackendDown />;
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Business Manager</h1>
        <p className="mt-1 text-sm text-gray-500">
          Your AI manager reviews the whole business, handles the routine work, and brings you only the
          decisions that need a human — prioritized by your goals.
        </p>
      </header>
      <ManagerConsole snapshot={snapshot} />
    </div>
  );
}
