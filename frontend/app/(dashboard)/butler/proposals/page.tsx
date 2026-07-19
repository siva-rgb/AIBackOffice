import { serverGet } from '@/lib/api/server';
import type { Proposal } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { ProposalList } from '@/components/butler/proposal-list';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Proposals — Kora' };

export default async function ProposalsPage() {
  let proposals: Proposal[];
  try {
    proposals = await serverGet<Proposal[]>('/api/proposals');
  } catch {
    return <BackendDown />;
  }
  return <ProposalList proposals={proposals} />;
}
