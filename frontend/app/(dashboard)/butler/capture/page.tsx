import { serverGet } from '@/lib/api/server';
import type { QuickCapture } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { CaptureReview } from '@/components/butler/capture-review';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Review queue — Kora' };

export default async function CaptureReviewPage() {
  let captures: QuickCapture[];
  try {
    captures = await serverGet<QuickCapture[]>('/api/butler/captures/review');
  } catch {
    return <BackendDown />;
  }
  return <CaptureReview captures={captures} />;
}
