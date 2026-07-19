import { serverGet } from '@/lib/api/server';
import type { Proposal } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { ProposalDetail } from '@/components/butler/proposal-detail';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Proposal — Kora' };

export default async function ProposalPage({ params }: { params: { proposalId: string } }) {
  let proposal: Proposal;
  try {
    proposal = await serverGet<Proposal>(`/api/proposals/${params.proposalId}`);
  } catch {
    return <BackendDown />;
  }
  return <ProposalDetail proposal={proposal} />;
}
