import { serverGet } from '@/lib/api/server';
import type { DriveDoc } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { DriveView } from '@/components/drive/drive-view';
import { FolderPicker } from '@/components/drive/folder-picker';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Drive — Kora' };

export default async function DrivePage() {
  let docs: DriveDoc[];
  try {
    docs = await serverGet<DriveDoc[]>('/api/drive/cache');
  } catch {
    return <BackendDown />;
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Drive</h1>
        <p className="mt-1 text-sm text-gray-500">
          Kora reads documents in the folder you choose, plus Meet transcripts, then routes them
          automatically — transcripts become meetings, contracts get queued for review.
        </p>
      </header>
      <FolderPicker />
      <DriveView docs={docs} />
    </div>
  );
}
