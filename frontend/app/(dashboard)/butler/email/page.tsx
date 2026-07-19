import { serverGet } from '@/lib/api/server';
import type { EmailIntel } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { EmailIntelView } from '@/components/email/email-intel-view';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Email intel — Kora' };

export default async function EmailPage() {
  let intel: EmailIntel[];
  try {
    intel = await serverGet<EmailIntel[]>('/api/gmail/intel');
  } catch {
    return <BackendDown />;
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Email intel</h1>
        <p className="mt-1 text-sm text-gray-500">
          Kora&apos;s analysis of your email threads with clients — relationship health, pending commitments, and suggested actions.
        </p>
      </header>
      <EmailIntelView intel={intel} />
    </div>
  );
}
