import { LoadingRegion, SkeletonCard, SkeletonPageHeading, SkeletonStatCards } from '@/components/ui';

// Shown the instant this route is requested. Without it Next keeps the previous
// page on screen for the whole server round trip and the click looks ignored.
export default function Loading() {
  return (
    <LoadingRegion label="Loading cash flow">
      <SkeletonPageHeading />
      <SkeletonStatCards count={4} />
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <SkeletonCard rows={4} />
        <SkeletonCard rows={4} />
      </div>
    </LoadingRegion>
  );
}
