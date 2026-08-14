import { LoadingRegion, SkeletonCard, SkeletonPageHeading, SkeletonStatCards } from '@/components/ui';

// Shown the instant this route is requested. Without it Next keeps the previous
// page on screen for the whole server round trip and the click looks ignored.
export default function Loading() {
  return (
    <LoadingRegion label="Loading AI agents">
      <SkeletonPageHeading />
      <SkeletonStatCards count={5} />
      <div className="mt-6"><SkeletonCard rows={5} /></div>
    </LoadingRegion>
  );
}
