import { serverGet } from '@/lib/api/server';
import type { Client } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { ProposalWizard } from '@/components/butler/proposal-wizard';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'New proposal — Kora' };

export default async function NewProposalPage() {
  let clients: Client[];
  try {
    clients = await serverGet<Client[]>('/api/clients');
  } catch {
    return <BackendDown />;
  }
  return <ProposalWizard clients={clients} />;
}
