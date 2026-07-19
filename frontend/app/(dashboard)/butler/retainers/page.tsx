import { serverGet } from '@/lib/api/server';
import type { Retainer, Client } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { RetainerList } from '@/components/butler/retainer-list';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Retainers — Kora' };

export default async function RetainersPage() {
  let retainers: Retainer[];
  let clients: Client[];
  try {
    [retainers, clients] = await Promise.all([
      serverGet<Retainer[]>('/api/retainers'),
      serverGet<Client[]>('/api/clients'),
    ]);
  } catch {
    return <BackendDown />;
  }
  return <RetainerList retainers={retainers} clients={clients} />;
}
