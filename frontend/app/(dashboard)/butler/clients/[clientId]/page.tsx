import { serverGet } from '@/lib/api/server';
import type { ClientDetail } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { ClientWorkspace } from '@/components/butler/client-workspace';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Client — Kora' };

export default async function ClientPage({ params }: { params: { clientId: string } }) {
  let detail: ClientDetail;
  try {
    detail = await serverGet<ClientDetail>(`/api/clients/${params.clientId}`);
  } catch {
    return <BackendDown />;
  }
  return (
    <div className="pb-6">
      <ClientWorkspace detail={detail} />
    </div>
  );
}
