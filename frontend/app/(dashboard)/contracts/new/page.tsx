import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { Card } from '@/components/ui';
import { ContractWizard } from '@/components/contracts/contract-wizard';

export default function NewContractPage() {
  return (
    <div className="space-y-6">
      <Link href="/contracts" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft size={15} /> Back to contracts
      </Link>
      <header>
        <h1 className="text-2xl font-bold text-gray-900">New contract</h1>
        <p className="mt-1 text-sm text-gray-500">
          Three quick steps. Kora drafts a structured contract with plain-English clause explanations.
        </p>
      </header>
      <Card className="p-6">
        <ContractWizard />
      </Card>
    </div>
  );
}
