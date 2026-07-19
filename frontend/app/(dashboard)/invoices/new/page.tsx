import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { Card } from '@/components/ui';
import { NewInvoiceForm } from '@/components/invoices/new-invoice-form';

export default function NewInvoicePage() {
  return (
    <div className="space-y-6">
      <Link href="/invoices" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900">
        <ArrowLeft size={15} /> Back to invoices
      </Link>
      <header>
        <h1 className="text-2xl font-bold text-gray-900">New invoice</h1>
        <p className="mt-1 text-sm text-gray-500">
          Create an invoice. Once sent, Kora&apos;s agent follows up automatically if it goes overdue.
        </p>
      </header>
      <Card className="p-6">
        <NewInvoiceForm />
      </Card>
    </div>
  );
}
