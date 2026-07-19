'use client';

import Link from 'next/link';
import { FileText, Plus, ArrowLeft } from 'lucide-react';
import { Card, CardHeader, Badge } from '@/components/ui';
import { formatMoney, formatDate } from '@/lib/utils';
import type { Proposal } from '@/lib/api/types';

export function ProposalList({ proposals }: { proposals: Proposal[] }) {
  return (
    <div className="space-y-6">
      <Link href="/butler" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft size={15} /> Back to Butler
      </Link>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Proposals</h1>
          <p className="mt-1 text-sm text-gray-500">Win the work first. When a client accepts, Kora turns it into a contract.</p>
        </div>
        <Link href="/butler/proposals/new" className="inline-flex items-center gap-1.5 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700">
          <Plus size={15} /> New proposal
        </Link>
      </div>

      <Card>
        {proposals.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-14 text-center">
            <FileText className="text-gray-300" size={30} />
            <p className="mt-3 text-sm font-medium text-gray-900">Proposals close deals before a contract exists</p>
            <p className="mt-1 max-w-md text-sm text-gray-500">
              Generate a professional proposal in two minutes. When the client accepts, Kora turns it into a contract automatically.
            </p>
            <Link href="/butler/proposals/new" className="mt-4 inline-flex items-center gap-1 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700">
              <Plus size={14} /> Create first proposal
            </Link>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {proposals.map((p) => (
              <li key={p.id}>
                <Link href={`/butler/proposals/${p.id}`} className="flex items-center justify-between px-5 py-4 hover:bg-gray-50">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-gray-900">{p.title}</span>
                      <Badge value={p.status} />
                    </div>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {p.proposalNumber} · {formatMoney(p.totalAmount, p.currency)} · {p.pricingType} · {formatDate(p.createdAt)}
                    </p>
                  </div>
                  {p.contractId && <span className="text-xs font-medium text-emerald-600">Contract created</span>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
