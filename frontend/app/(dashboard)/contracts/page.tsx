import Link from 'next/link';
import { Plus, FileSignature, ScanSearch } from 'lucide-react';
import { serverGet } from '@/lib/api/server';
import type { Contract } from '@/lib/api/types';
import { Card } from '@/components/ui';
import { BackendDown } from '@/components/backend-down';
import { ContractList } from '@/components/contracts/contract-list';

export const dynamic = 'force-dynamic';

export default async function ContractsPage() {
  let contracts: Contract[];
  try {
    contracts = await serverGet<Contract[]>('/api/contracts');
  } catch {
    return <BackendDown />;
  }

  return (
    <div className="space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Contracts</h1>
          <p className="mt-1 text-sm text-gray-500">
            Describe a deal in plain English — AI drafts a professional, jurisdiction-aware contract.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/contracts/review"
            className="inline-flex items-center gap-2 rounded-lg border border-kora-200 px-4 py-2 text-sm font-semibold text-kora-700 hover:bg-kora-50"
          >
            <ScanSearch size={16} /> Review a contract
          </Link>
          <Link
            href="/contracts/new"
            className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700"
          >
            <Plus size={16} /> New contract
          </Link>
        </div>
      </header>

      {contracts.length === 0 ? (
        <Card className="flex flex-col items-center justify-center py-16 text-center">
          <FileSignature className="text-kora-600" size={32} />
          <h2 className="mt-4 text-lg font-semibold text-gray-900">Generate your first contract</h2>
          <p className="mt-1 max-w-sm text-sm text-gray-500">
            Describe your deal in plain English. AI drafts a professional contract in ~20 seconds.
          </p>
          <Link
            href="/contracts/new"
            className="mt-6 inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700"
          >
            <Plus size={16} /> Create contract
          </Link>
        </Card>
      ) : (
        <ContractList contracts={contracts} />
      )}
    </div>
  );
}
