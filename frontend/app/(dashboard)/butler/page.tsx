import { serverGet } from '@/lib/api/server';
import type { ButlerSnapshot, Client } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { ButlerHome } from '@/components/butler/butler-home';
import { QuickCapture } from '@/components/butler/quick-capture';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Butler — Kora' };

export default async function ButlerPage() {
  let snapshot: ButlerSnapshot;
  let clients: Client[];
  try {
    [snapshot, clients] = await Promise.all([
      serverGet<ButlerSnapshot>('/api/butler'),
      serverGet<Client[]>('/api/clients?status=active'),
    ]);
  } catch {
    return <BackendDown />;
  }

  return (
    <div className="space-y-8 pb-20">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Butler</h1>
        <p className="mt-1 text-sm text-gray-500">
          Your AI chief of staff. Kora knows your clients, the work in flight, and the money — and tells you
          what matters before it becomes a problem.
        </p>
      </header>
      <ButlerHome snapshot={snapshot} clients={clients} />
      <QuickCapture />
    </div>
  );
}
