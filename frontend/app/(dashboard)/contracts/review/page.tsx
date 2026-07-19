import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { ContractReviewer } from '@/components/contracts/contract-reviewer';

export const metadata = { title: 'Review a contract — Kora' };

export default function ReviewContractPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <Link href="/contracts" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
          <ArrowLeft size={15} /> Contracts
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Review a contract</h1>
        <p className="mt-1 text-sm text-gray-500">
          Received an agreement for a deal? Upload or paste it and Kora&apos;s AI flags risky clauses,
          one-sided terms, and missing protections — before you sign.
        </p>
      </div>
      <ContractReviewer />
    </div>
  );
}
