import { serverGet } from '@/lib/api/server';
import type { Meeting } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { MeetingsView } from '@/components/meetings/meetings-view';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Meetings — Kora' };

export default async function MeetingsPage() {
  let meetings: Meeting[];
  try {
    meetings = await serverGet<Meeting[]>('/api/meetings');
  } catch {
    return <BackendDown />;
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Meetings</h1>
        <p className="mt-1 text-sm text-gray-500">
          Upload transcripts or quick notes — Kora extracts action items, commitments, and risks automatically.
        </p>
      </header>
      <MeetingsView meetings={meetings} />
    </div>
  );
}
